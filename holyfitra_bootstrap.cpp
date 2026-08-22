// Holy Fitra Stage-0 bootstrap compiler, dependency-free C++17 seed.
//
// The seed emits textual LLVM IR and supports the compiler-core substrate:
// scalar values, fixed arrays, named structs, string literals, indexing,
// field access, direct calls, if/else, while, locals, and returns.
//
// Build:
//   clang++ -std=c++17 -O2 -Wall -Wextra -pedantic holyfitra_bootstrap.cpp -o holyfitra_bootstrap
// Emit:
//   ./holyfitra_bootstrap --target=x86_64-pc-linux-gnu input.hf -o input.ll
//   clang input.ll -O2 -o input
// AArch64 object:
//   ./holyfitra_bootstrap --target=aarch64-linux-android21 input.hf -o input.ll
//   clang --target=aarch64-linux-android21 -c input.ll -o input.aarch64.o

#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <set>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace hf0 {

constexpr std::size_t kMaxSourceBytes = 8u * 1024u * 1024u;
constexpr std::size_t kMaxTokens = 1u << 20;
constexpr std::size_t kMaxNesting = 512;
constexpr std::size_t kMaxArrayElements = 1u << 20;
constexpr std::size_t kMaxStringBytes = 1u << 20;

struct SourcePosition final {
    int line = 0;
    int column = 0;
};

struct SourceSpan final {
    SourcePosition begin;
    SourcePosition end;
    bool valid() const { return begin.line > 0 && begin.column > 0; }
    static SourceSpan point(int line, int column, int width = 1) {
        SourceSpan span{{line, column}, {line, column + (width > 0 ? width : 1)}};
        return span;
    }
};

struct DiagnosticNote final {
    std::string message;
    SourceSpan span;
};

struct Diagnostic final : std::runtime_error {
    std::string code;
    SourceSpan span;
    std::vector<DiagnosticNote> notes;
    Diagnostic(std::string message, int line = 0, int column = 0, std::string code = "HF0001")
        : std::runtime_error(std::move(message)), code(std::move(code)), span(SourceSpan::point(line, column)) {}
    Diagnostic& addNote(std::string message, SourceSpan note_span = {}) {
        notes.push_back({std::move(message), note_span});
        return *this;
    }
};

[[noreturn]] static void fail(const std::string& message, int line = 0, int column = 0) {
    throw Diagnostic(message, line, column);
}

static std::string location(int line, int column) {
    return line > 0 ? " at " + std::to_string(line) + ":" + std::to_string(column) : "";
}

enum class TokenKind { Eof, Identifier, Integer, String, Arrow, Operator, Punctuation };

struct Token final {
    TokenKind kind;
    std::string text;
    int line;
    int column;
    SourceSpan span;
    Token(TokenKind kind, std::string text, int line, int column)
        : kind(kind), text(std::move(text)), line(line), column(column), span(SourceSpan::point(line, column)) {}
};

class Lexer final {
public:
    explicit Lexer(std::string source) : source_(std::move(source)) {}

    std::vector<Token> run() {
        std::vector<Token> result;
        while (position_ < source_.size()) {
            const char c = source_[position_];
            if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { advance(); continue; }
            if ((c == '/' && peek(1) == '/') || c == '#') { skipComment(); continue; }
            const int line = line_;
            const int column = column_;
            if (identifierStart(c)) {
                std::string text;
                while (position_ < source_.size() && identifierContinue(source_[position_])) { text.push_back(source_[position_]); advance(); }
                result.push_back({TokenKind::Identifier, std::move(text), line, column});
                continue;
            }
            if (c >= '0' && c <= '9') {
                std::string text;
                while (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') { text.push_back(source_[position_]); advance(); }
                result.push_back({TokenKind::Integer, std::move(text), line, column});
                continue;
            }
            if (c == '"') {
                advance();
                std::string text;
                while (position_ < source_.size() && source_[position_] != '"') {
                    if (source_[position_] == '\\' && peek(1) == '"') { text.push_back('"'); advance(); advance(); }
                    else if (source_[position_] == '\\' && peek(1) == 'n') { text.push_back('\n'); advance(); advance(); }
                    else { text.push_back(source_[position_]); advance(); }
                }
                if (position_ >= source_.size()) fail("unterminated string literal" + location(line, column), line, column);
                if (text.size() > kMaxStringBytes) fail("string literal exceeds the 1 MiB limit", line, column);
                advance();
                result.push_back({TokenKind::String, std::move(text), line, column});
                continue;
            }
            if (c == '-' && peek(1) == '>') { advance(); advance(); result.push_back({TokenKind::Arrow, "->", line, column}); continue; }
            const std::string two = std::string() + c + peek(1);
            if (two == "==" || two == "!=" || two == "<=" || two == ">=" || two == "&&" || two == "||") {
                advance(); advance(); result.push_back({TokenKind::Operator, two, line, column}); continue;
            }
            if (std::string("+-*/=<>!").find(c) != std::string::npos) { advance(); result.push_back({TokenKind::Operator, std::string(1, c), line, column}); continue; }
            if (std::string("{}(),:;[].").find(c) != std::string::npos) { advance(); result.push_back({TokenKind::Punctuation, std::string(1, c), line, column}); continue; }
            fail(std::string("unexpected character '") + c + "'" + location(line, column), line, column);
        }
        if (result.size() > kMaxTokens) fail("source token limit exceeded", line_, column_);
        result.push_back({TokenKind::Eof, "", line_, column_});
        return result;
    }

private:
    static bool identifierStart(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; }
    static bool identifierContinue(char c) { return identifierStart(c) || (c >= '0' && c <= '9'); }
    char peek(std::size_t offset) const { const auto i = position_ + offset; return i < source_.size() ? source_[i] : '\0'; }
    void advance() { if (source_[position_] == '\n') { ++line_; column_ = 1; } else ++column_; ++position_; }
    void skipComment() { while (position_ < source_.size() && source_[position_] != '\n') advance(); }
    std::string source_;
    std::size_t position_ = 0;
    int line_ = 1;
    int column_ = 1;
};

enum class TypeKind { I32, I64, Bool, Void, String, Handle, File, Buffer, Array, DynamicArray, Struct };

struct Type final {
    TypeKind kind = TypeKind::Void;
    std::string name;
    std::size_t count = 0;
    std::shared_ptr<Type> element;
    std::vector<std::pair<std::string, Type>> fields;

    static Type scalar(TypeKind kind) { Type type; type.kind = kind; return type; }
    static Type array(std::size_t count, Type element) { Type type; type.kind = TypeKind::Array; type.count = count; type.element = std::make_shared<Type>(std::move(element)); return type; }
    static Type dynamicArray(Type element) { Type type; type.kind = TypeKind::DynamicArray; type.element = std::make_shared<Type>(std::move(element)); return type; }
    static Type structure(std::string name, std::vector<std::pair<std::string, Type>> fields = {}) { Type type; type.kind = TypeKind::Struct; type.name = std::move(name); type.fields = std::move(fields); return type; }

    bool operator==(const Type& other) const {
        if (kind != other.kind) return false;
        if (kind == TypeKind::Struct) return name == other.name;
        if (kind == TypeKind::Array || kind == TypeKind::DynamicArray) return count == other.count && element && other.element && *element == *other.element;
        return true;
    }
    bool operator!=(const Type& other) const { return !(*this == other); }

    std::string display() const {
        switch (kind) {
            case TypeKind::I32: return "i32";
            case TypeKind::I64: return "i64";
            case TypeKind::Bool: return "bool";
            case TypeKind::Void: return "void";
            case TypeKind::String: return "string";
            case TypeKind::Handle: return "handle";
            case TypeKind::File: return "file";
            case TypeKind::Buffer: return "buf";
            case TypeKind::Array: return "[" + std::to_string(count) + "]" + element->display();
            case TypeKind::DynamicArray: return "dyn<" + element->display() + ">";
            case TypeKind::Struct: return name;
        }
        return "unknown";
    }
    std::string llvm() const {
        switch (kind) {
            case TypeKind::I32: return "i32";
            case TypeKind::I64: return "i64";
            case TypeKind::Bool: return "i1";
            case TypeKind::Void: return "void";
            case TypeKind::String: return "ptr";
            case TypeKind::Handle: return "ptr";
            case TypeKind::File: return "ptr";
            case TypeKind::Buffer: return "ptr";
            case TypeKind::Array: return "[" + std::to_string(count) + " x " + element->llvm() + "]";
            case TypeKind::DynamicArray: return "ptr";
            case TypeKind::Struct: return "%struct." + name;
        }
        return "void";
    }
};

// Keep the typo-prone TypeKind spelling localized through a compile-time alias.
using TypeKindKind = TypeKind;

struct StructDecl final {
    std::string name;
    std::vector<std::pair<std::string, Type>> fields;
    int line = 0;
    SourceSpan span;
    StructDecl(std::string name, std::vector<std::pair<std::string, Type>> fields, int line)
        : name(std::move(name)), fields(std::move(fields)), line(line), span(SourceSpan::point(line, 1)) {}
};
struct Expr;
struct Statement;
using ExprPtr = std::unique_ptr<Expr>;
using StatementPtr = std::unique_ptr<Statement>;

struct Expr {
    enum class Kind { Integer, Boolean, String, Name, Unary, Binary, Call, Array, Struct, Field, Index };
    Expr(Kind kind, int line, int column) : kind(kind), line(line), column(column), span(SourceSpan::point(line, column)) {}
    virtual ~Expr() = default;
    Kind kind;
    int line;
    int column;
    SourceSpan span;
};
struct IntegerExpr final : Expr { IntegerExpr(std::int64_t v, int l, int c) : Expr(Kind::Integer,l,c), value(v) {} std::int64_t value; };
struct BooleanExpr final : Expr { BooleanExpr(bool v, int l, int c) : Expr(Kind::Boolean,l,c), value(v) {} bool value; };
struct StringExpr final : Expr { StringExpr(std::string v, int l, int c) : Expr(Kind::String,l,c), value(std::move(v)) {} std::string value; };
struct NameExpr final : Expr { NameExpr(std::string v, int l, int c) : Expr(Kind::Name,l,c), name(std::move(v)) {} std::string name; };
struct UnaryExpr final : Expr { UnaryExpr(std::string o, ExprPtr e, int l, int c) : Expr(Kind::Unary,l,c), op(std::move(o)), operand(std::move(e)) {} std::string op; ExprPtr operand; };
struct BinaryExpr final : Expr { BinaryExpr(std::string o, ExprPtr a, ExprPtr b, int l, int c) : Expr(Kind::Binary,l,c), op(std::move(o)), left(std::move(a)), right(std::move(b)) {} std::string op; ExprPtr left; ExprPtr right; };
struct CallExpr final : Expr { CallExpr(std::string n, std::vector<ExprPtr> a, int l, int c) : Expr(Kind::Call,l,c), name(std::move(n)), arguments(std::move(a)) {} std::string name; std::vector<ExprPtr> arguments; };
struct ArrayExpr final : Expr { ArrayExpr(std::vector<ExprPtr> e, int l, int c) : Expr(Kind::Array,l,c), elements(std::move(e)) {} std::vector<ExprPtr> elements; };
struct StructExpr final : Expr { StructExpr(std::string n, std::vector<std::pair<std::string,ExprPtr>> f, int l, int c) : Expr(Kind::Struct,l,c), name(std::move(n)), fields(std::move(f)) {} std::string name; std::vector<std::pair<std::string,ExprPtr>> fields; };
struct FieldExpr final : Expr { FieldExpr(ExprPtr b, std::string f, int l, int c) : Expr(Kind::Field,l,c), base(std::move(b)), field(std::move(f)) {} ExprPtr base; std::string field; };
struct IndexExpr final : Expr { IndexExpr(ExprPtr b, ExprPtr i, int l, int c) : Expr(Kind::Index,l,c), base(std::move(b)), index(std::move(i)) {} ExprPtr base; ExprPtr index; };

struct Statement { enum class Kind { Let, Assignment, Return, If, While, Expression }; Statement(Kind k,int l,int c):kind(k),line(l),column(c),span(SourceSpan::point(l,c)){} virtual ~Statement()=default; Kind kind; int line; int column; SourceSpan span; };
struct LetStatement final : Statement { LetStatement(std::string n,std::optional<Type> t,ExprPtr v,bool m,int l,int c):Statement(Kind::Let,l,c),name(std::move(n)),declared(std::move(t)),value(std::move(v)),mutable_value(m){} std::string name; std::optional<Type> declared; ExprPtr value; bool mutable_value; };
struct AssignmentStatement final : Statement { AssignmentStatement(std::string n,ExprPtr v,int l,int c):Statement(Kind::Assignment,l,c),name(std::move(n)),value(std::move(v)){} std::string name; ExprPtr value; };
struct ReturnStatement final : Statement { ReturnStatement(ExprPtr v,int l,int c):Statement(Kind::Return,l,c),value(std::move(v)){} ExprPtr value; };
struct IfStatement final : Statement { IfStatement(ExprPtr c,std::vector<StatementPtr> a,std::vector<StatementPtr>b,int l,int col):Statement(Kind::If,l,col),condition(std::move(c)),then_body(std::move(a)),else_body(std::move(b)){} ExprPtr condition; std::vector<StatementPtr> then_body; std::vector<StatementPtr> else_body; };
struct WhileStatement final : Statement { WhileStatement(ExprPtr c,std::vector<StatementPtr>b,int l,int col):Statement(Kind::While,l,col),condition(std::move(c)),body(std::move(b)){} ExprPtr condition; std::vector<StatementPtr> body; };
struct ExpressionStatement final : Statement { ExpressionStatement(ExprPtr e,int l,int c):Statement(Kind::Expression,l,c),expression(std::move(e)){} ExprPtr expression; };

struct Parameter final { std::string name; Type type; };
struct Function final {
    std::string name;
    std::vector<Parameter> parameters;
    Type return_type;
    std::vector<StatementPtr> body;
    int line = 0;
    bool builtin = false;
    SourceSpan span;
    Function(std::string name, std::vector<Parameter> parameters, Type return_type, std::vector<StatementPtr> body, int line, bool builtin = false)
        : name(std::move(name)), parameters(std::move(parameters)), return_type(std::move(return_type)), body(std::move(body)), line(line), builtin(builtin), span(SourceSpan::point(line, 1)) {}
};
struct Program final { std::string module = "anonymous"; std::vector<StructDecl> structs; std::vector<Function> functions; };

static const std::vector<Function>& builtinFunctions() {
    static const std::vector<Function> functions = [] {
        std::vector<Function> result;
        result.emplace_back(Function{"hf_dyn_i32_new", {{"capacity", Type::scalar(TypeKind::I64)}}, Type::dynamicArray(Type::scalar(TypeKind::I32)), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_push", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}, {"value", Type::scalar(TypeKind::I32)}}, Type::scalar(TypeKind::Bool), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_len", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}}, Type::scalar(TypeKind::I64), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_get", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}, {"index", Type::scalar(TypeKind::I64)}}, Type::scalar(TypeKind::I32), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_free", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}}, Type::scalar(TypeKind::Void), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_len32", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}}, Type::scalar(TypeKind::I32), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_get32", {{"array", Type::dynamicArray(Type::scalar(TypeKind::I32))}, {"index", Type::scalar(TypeKindKind::I32)}}, Type::scalar(TypeKindKind::I32), {}, 0, true});
        result.emplace_back(Function{"hf_dyn_i32_set32", {{"array", Type::dynamicArray(Type::scalar(TypeKindKind::I32))}, {"index", Type::scalar(TypeKindKind::I32)}, {"value", Type::scalar(TypeKindKind::I32)}}, Type::scalar(TypeKindKind::Void), {}, 0, true});
        result.emplace_back(Function{"hf_string_len32", {{"text", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKindKind::I32), {}, 0, true});
        result.emplace_back(Function{"hf_string_byte32", {{"text", Type::scalar(TypeKind::String)}, {"index", Type::scalar(TypeKindKind::I32)}}, Type::scalar(TypeKindKind::I32), {}, 0, true});
        result.emplace_back(Function{"hf_file_open", {{"path", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::File), {}, 0, true});
        result.emplace_back(Function{"hf_file_read_all", {{"file", Type::scalar(TypeKind::File)}}, Type::scalar(TypeKind::String), {}, 0, true});
        result.emplace_back(Function{"hf_file_close", {{"file", Type::scalar(TypeKind::File)}}, Type::scalar(TypeKind::Void), {}, 0, true});
        result.emplace_back(Function{"hf_read_text", {{"path", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::String), {}, 0, true});
        result.emplace_back(Function{"hf_write_text", {{"path", Type::scalar(TypeKind::String)}, {"text", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::Bool), {}, 0, true});
        result.emplace_back(Function{"hf_string_free", {{"text", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::Void), {}, 0, true});
        result.emplace_back(Function{"hf_string_slice32", {{"text", Type::scalar(TypeKind::String)}, {"start", Type::scalar(TypeKind::I32)}, {"length", Type::scalar(TypeKind::I32)}}, Type::scalar(TypeKind::String), {}, 0, true});
        result.emplace_back(Function{"hf_path_canonicalize", {{"path", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::String), {}, 0, true});
        result.emplace_back(Function{"hf_buf_new", {{"capacity", Type::scalar(TypeKind::I64)}}, Type::scalar(TypeKind::Buffer), {}, 0, true});
        result.emplace_back(Function{"hf_buf_append_byte", {{"buffer", Type::scalar(TypeKind::Buffer)}, {"value", Type::scalar(TypeKind::I32)}}, Type::scalar(TypeKind::Bool), {}, 0, true});
        result.emplace_back(Function{"hf_buf_append_str", {{"buffer", Type::scalar(TypeKind::Buffer)}, {"text", Type::scalar(TypeKind::String)}}, Type::scalar(TypeKind::Bool), {}, 0, true});
        result.emplace_back(Function{"hf_buf_append_i32", {{"buffer", Type::scalar(TypeKind::Buffer)}, {"value", Type::scalar(TypeKind::I32)}}, Type::scalar(TypeKind::Bool), {}, 0, true});
        result.emplace_back(Function{"hf_buf_finish", {{"buffer", Type::scalar(TypeKind::Buffer)}}, Type::scalar(TypeKind::String), {}, 0, true});
        result.emplace_back(Function{"hf_buf_free", {{"buffer", Type::scalar(TypeKind::Buffer)}}, Type::scalar(TypeKind::Void), {}, 0, true});
        return result;
    }();
    return functions;
}

static const Function* findBuiltin(const std::string& name) {
    for (const auto& function : builtinFunctions()) if (function.name == name) return &function;
    return nullptr;
}

class Parser final {
public:
    explicit Parser(std::vector<Token> tokens) : tokens_(std::move(tokens)) {}
    Program parse() {
        Program program;
        if (accept(TokenKind::Identifier,"module")) program.module = expect(TokenKind::Identifier,"module name").text;
        while (!is(TokenKind::Eof)) {
            if (accept(TokenKind::Identifier,"struct")) program.structs.push_back(parseStruct());
            else if (accept(TokenKind::Identifier,"fn")) program.functions.push_back(parseFunction());
            else unexpected("struct or function");
        }
        if (program.functions.empty()) fail("program must declare at least one function");
        return program;
    }
private:
    const Token& current() const { return tokens_.at(index_); }
    const Token& lookahead(std::size_t offset) const { const std::size_t i = index_ + offset; return tokens_.at(i < tokens_.size() ? i : tokens_.size() - 1); }
    bool is(TokenKind k) const { return current().kind == k; }
    bool isText(TokenKind k,const std::string& t) const { return current().kind==k && current().text==t; }
    Token advance() { Token t=current(); if(index_+1<tokens_.size())++index_; return t; }
    bool accept(TokenKind k,const std::string& t="") { if(current().kind==k && (t.empty()||current().text==t)){advance();return true;} return false; }
    Token expect(TokenKind k,const std::string& what) { if(!is(k)) unexpected(what); return advance(); }
    void expectText(TokenKind k,const std::string& t) { if(!isText(k,t)) unexpected("'"+t+"'"); advance(); }
    [[noreturn]] void unexpected(const std::string& what) const { fail("expected "+what+", got '"+current().text+"'"+location(current().line,current().column),current().line,current().column); }
    StructDecl parseStruct() {
        Token name=expect(TokenKind::Identifier,"struct name"); expectText(TokenKind::Punctuation,"{"); StructDecl decl{name.text,{},name.line};
        while(!accept(TokenKind::Punctuation,"}")) { Token field=expect(TokenKind::Identifier,"field name"); expectText(TokenKind::Punctuation,":"); decl.fields.push_back({field.text,parseType()}); accept(TokenKind::Punctuation,";"); if(!isText(TokenKind::Punctuation,"}")) accept(TokenKind::Punctuation,","); }
        return decl;
    }
    Function parseFunction() {
        Token name=expect(TokenKind::Identifier,"function name"); expectText(TokenKind::Punctuation,"("); std::vector<Parameter> params;
        if(!accept(TokenKind::Punctuation,")")) { while(true) { Token p=expect(TokenKind::Identifier,"parameter name"); expectText(TokenKind::Punctuation,":"); params.push_back({p.text,parseType()}); if(accept(TokenKind::Punctuation,")"))break; expectText(TokenKind::Punctuation,","); } }
        expect(TokenKind::Arrow,"'->'"); Type ret=parseType(); return Function{name.text,std::move(params),ret,parseBlock(),name.line};
    }
    Type parseType() {
        if(accept(TokenKind::Punctuation,"[")) { Token n=expect(TokenKind::Integer,"array length"); expectText(TokenKind::Punctuation,"]"); std::size_t count=static_cast<std::size_t>(std::stoull(n.text)); if(count==0) fail("array length must be positive",n.line,n.column); if(count>kMaxArrayElements) fail("array length exceeds the v1 limit",n.line,n.column); return Type::array(count,parseType()); }
        Token t=expect(TokenKind::Identifier,"type"); if(t.text=="i32")return Type::scalar(TypeKind::I32); if(t.text=="i64")return Type::scalar(TypeKind::I64); if(t.text=="bool")return Type::scalar(TypeKind::Bool); if(t.text=="void")return Type::scalar(TypeKind::Void); if(t.text=="string")return Type::scalar(TypeKind::String); if(t.text=="handle")return Type::scalar(TypeKind::Handle); if(t.text=="file")return Type::scalar(TypeKind::File); if(t.text=="buf")return Type::scalar(TypeKind::Buffer); if(t.text=="dyn"){expectText(TokenKind::Operator,"<");Type element=parseType();expectText(TokenKind::Operator,">");return Type::dynamicArray(std::move(element));} return Type::structure(t.text);
    }
    std::vector<StatementPtr> parseBlock() {
        if (++block_depth_ > kMaxNesting) fail("block nesting limit exceeded", current().line, current().column);
        expectText(TokenKind::Punctuation,"{"); std::vector<StatementPtr> body;
        while(!accept(TokenKind::Punctuation,"}")){if(is(TokenKind::Eof))unexpected("'}'");body.push_back(parseStatement());}
        --block_depth_;
        return body;
    }
    StatementPtr parseStatement() {
        if(is(TokenKind::Identifier)&&lookahead(1).kind==TokenKind::Operator&&lookahead(1).text=="="){Token name=advance();advance();auto value=parseExpression();accept(TokenKind::Punctuation,";");return std::make_unique<AssignmentStatement>(name.text,std::move(value),name.line,name.column);}
        if(isText(TokenKind::Identifier,"let")||isText(TokenKind::Identifier,"var")){Token kw=advance(),name=expect(TokenKind::Identifier,"local name");std::optional<Type> type;if(accept(TokenKind::Punctuation,":"))type=parseType();expectText(TokenKind::Operator,"=");auto value=parseExpression();accept(TokenKind::Punctuation,";");return std::make_unique<LetStatement>(name.text,type,std::move(value),kw.text=="var",name.line,name.column);}
        if(accept(TokenKind::Identifier,"return")){Token k=tokens_[index_-1];ExprPtr value;if(!isText(TokenKind::Punctuation,";")&&!isText(TokenKind::Punctuation,"}"))value=parseExpression();accept(TokenKind::Punctuation,";");return std::make_unique<ReturnStatement>(std::move(value),k.line,k.column);}
        if(accept(TokenKind::Identifier,"if")){Token k=tokens_[index_-1];auto c=parseExpression();auto a=parseBlock(),b=std::vector<StatementPtr>{};if(accept(TokenKind::Identifier,"else"))b=parseBlock();return std::make_unique<IfStatement>(std::move(c),std::move(a),std::move(b),k.line,k.column);}
        if(accept(TokenKind::Identifier,"while")){Token k=tokens_[index_-1];auto c=parseExpression();auto b=parseBlock();return std::make_unique<WhileStatement>(std::move(c),std::move(b),k.line,k.column);}
        Token k=current();auto e=parseExpression();accept(TokenKind::Punctuation,";");return std::make_unique<ExpressionStatement>(std::move(e),k.line,k.column);
    }
    ExprPtr parseExpression(){
        if (++expression_depth_ > kMaxNesting) fail("expression nesting limit exceeded", current().line, current().column);
        ExprPtr result = parseLogicalOr();
        --expression_depth_;
        return result;
    }
    ExprPtr parseLogicalOr(){auto e=parseLogicalAnd();while(isText(TokenKind::Operator,"||")){Token o=advance();e=std::make_unique<BinaryExpr>(o.text,std::move(e),parseLogicalAnd(),o.line,o.column);}return e;}
    ExprPtr parseLogicalAnd(){auto e=parseComparison();while(isText(TokenKind::Operator,"&&")){Token o=advance();e=std::make_unique<BinaryExpr>(o.text,std::move(e),parseComparison(),o.line,o.column);}return e;}
    ExprPtr parseComparison(){auto e=parseAdditive();while(is(TokenKind::Operator)&&(current().text=="=="||current().text=="!="||current().text=="<"||current().text=="<="||current().text==">"||current().text==">=")){Token o=advance();e=std::make_unique<BinaryExpr>(o.text,std::move(e),parseAdditive(),o.line,o.column);}return e;}
    ExprPtr parseAdditive(){auto e=parseMultiplicative();while(is(TokenKind::Operator)&&(current().text=="+"||current().text=="-")){Token o=advance();e=std::make_unique<BinaryExpr>(o.text,std::move(e),parseMultiplicative(),o.line,o.column);}return e;}
    ExprPtr parseMultiplicative(){auto e=parseUnary();while(is(TokenKind::Operator)&&(current().text=="*"||current().text=="/")){Token o=advance();e=std::make_unique<BinaryExpr>(o.text,std::move(e),parseUnary(),o.line,o.column);}return e;}
    ExprPtr parseUnary(){if(isText(TokenKind::Operator,"-")||isText(TokenKind::Operator,"!")){Token o=advance();return std::make_unique<UnaryExpr>(o.text,parseUnary(),o.line,o.column);}return parsePostfix();}
    ExprPtr parsePostfix(){auto e=parsePrimary();while(true){if(accept(TokenKind::Punctuation,".")){Token f=expect(TokenKind::Identifier,"field name");e=std::make_unique<FieldExpr>(std::move(e),f.text,f.line,f.column);}else if(accept(TokenKind::Punctuation,"[")){Token i=current();auto idx=parseExpression();expectText(TokenKind::Punctuation,"]");e=std::make_unique<IndexExpr>(std::move(e),std::move(idx),i.line,i.column);}else break;}return e;}
    ExprPtr parsePrimary(){
        if(is(TokenKind::Integer)){Token t=advance();return std::make_unique<IntegerExpr>(std::stoll(t.text),t.line,t.column);}
        if(is(TokenKind::String)){Token t=advance();return std::make_unique<StringExpr>(t.text,t.line,t.column);}
        if(isText(TokenKind::Identifier,"true")||isText(TokenKind::Identifier,"false")){Token t=advance();return std::make_unique<BooleanExpr>(t.text=="true",t.line,t.column);}
                if(isText(TokenKind::Punctuation,"[")){Token t=advance();
std::vector<ExprPtr> e;if(!accept(TokenKind::Punctuation,"]")){while(true){e.push_back(parseExpression());if(accept(TokenKind::Punctuation,"]"))break;expectText(TokenKind::Punctuation,",");}}return std::make_unique<ArrayExpr>(std::move(e),t.line,t.column);}
        if(is(TokenKind::Identifier)){Token n=advance();if(accept(TokenKind::Punctuation,"(")){std::vector<ExprPtr>a;if(!accept(TokenKind::Punctuation,")")){while(true){a.push_back(parseExpression());if(accept(TokenKind::Punctuation,")"))break;expectText(TokenKind::Punctuation,",");}}return std::make_unique<CallExpr>(n.text,std::move(a),n.line,n.column);}if(isText(TokenKind::Punctuation,"{")&&lookahead(1).kind==TokenKind::Identifier&&lookahead(2).kind==TokenKind::Punctuation&&lookahead(2).text==":"){advance();std::vector<std::pair<std::string,ExprPtr>>f;while(!accept(TokenKind::Punctuation,"}")){Token k=expect(TokenKind::Identifier,"field name");expectText(TokenKind::Punctuation,":");f.push_back({k.text,parseExpression()});if(accept(TokenKind::Punctuation,"}"))break;expectText(TokenKind::Punctuation,",");}return std::make_unique<StructExpr>(n.text,std::move(f),n.line,n.column);}return std::make_unique<NameExpr>(n.text,n.line,n.column);}
        if(accept(TokenKind::Punctuation,"(")){auto e=parseExpression();expectText(TokenKind::Punctuation,")");return e;}
        unexpected("expression");
    }
    std::vector<Token> tokens_;std::size_t index_=0;std::size_t expression_depth_=0;std::size_t block_depth_=0;
};

class Validator final {
public:
    void run(const Program& program){structs_.clear();functions_.clear();for(const auto& s:program.structs){if(structs_.count(s.name))fail("duplicate struct '"+s.name+"'",s.line,1);structs_[s.name]=&s;}for(const auto& f:program.functions){if(functions_.count(f.name)||findBuiltin(f.name))fail("reserved or duplicate function '"+f.name+"'",f.line,1);functions_[f.name]=&f;}for(const auto& f:program.functions)validateFunction(f);}
private:
    bool compatible(const Expr& e,const Type& a,const Type& b)const{return a==b||(e.kind==Expr::Kind::Integer&&a.kind==TypeKind::I32&&b.kind==TypeKind::I64);}
    const Function* findFunction(const std::string& name) const { auto i=functions_.find(name); return i!=functions_.end()?i->second:findBuiltin(name); }
    const StructDecl& structure(const std::string& n,int l,int c)const{auto i=structs_.find(n);if(i==structs_.end())fail("unknown struct '"+n+"'",l,c);return *i->second;}
    Type infer(const Expr& e,std::unordered_map<std::string,Type>& vars)const{
        switch(e.kind){
            case Expr::Kind::Integer:return Type::scalar(TypeKind::I32);case Expr::Kind::Boolean:return Type::scalar(TypeKind::Bool);case Expr::Kind::String:return Type::scalar(TypeKind::String);
            case Expr::Kind::Name:{auto n=static_cast<const NameExpr&>(e).name;auto i=vars.find(n);if(i==vars.end())fail("unknown value '"+n+"'",e.line,e.column);return i->second;}
            case Expr::Kind::Unary:{auto&x=static_cast<const UnaryExpr&>(e);auto t=infer(*x.operand,vars);if(x.op=="-"&&(t.kind!=TypeKind::I32&&t.kind!=TypeKind::I64))fail("unary '-' requires integer",e.line,e.column);if(x.op=="!"&&t.kind!=TypeKind::Bool)fail("unary '!' requires bool",e.line,e.column);return t;}
            case Expr::Kind::Binary:{auto&x=static_cast<const BinaryExpr&>(e);auto a=infer(*x.left,vars),b=infer(*x.right,vars);if(a!=b)fail("binary operands have different types",e.line,e.column);if(x.op=="&&"||x.op=="||"){if(a.kind!=TypeKind::Bool)fail("logical operators require bool",e.line,e.column);return Type::scalar(TypeKind::Bool);}if(x.op=="=="||x.op=="!="||x.op=="<"||x.op=="<="||x.op==">"||x.op==">="){if(a.kind!=TypeKind::I32&&a.kind!=TypeKind::I64&&a.kind!=TypeKind::Bool)fail("unsupported comparison type",e.line,e.column);return Type::scalar(TypeKind::Bool);}if(a.kind!=TypeKind::I32&&a.kind!=TypeKind::I64)fail("arithmetic requires integer",e.line,e.column);return a;}
            case Expr::Kind::Call:{auto&x=static_cast<const CallExpr&>(e);const Function* fp=findFunction(x.name);if(!fp)fail("unknown function '"+x.name+"'",e.line,e.column);const auto&f=*fp;if(x.arguments.size()!=f.parameters.size())fail("wrong argument count",e.line,e.column);for(std::size_t i=0;i<x.arguments.size();++i){auto a=infer(*x.arguments[i],vars);if(!compatible(*x.arguments[i],a,f.parameters[i].type))fail("argument type mismatch",e.line,e.column);}return f.return_type;}
            case Expr::Kind::Array:{auto&x=static_cast<const ArrayExpr&>(e);if(x.elements.empty())fail("empty arrays require an explicit type",e.line,e.column);auto t=infer(*x.elements[0],vars);for(const auto&v:x.elements){auto a=infer(*v,vars);if(!compatible(*v,a,t))fail("array elements have different types",v->line,v->column);}return Type::array(x.elements.size(),t);}
            case Expr::Kind::Struct:{auto&x=static_cast<const StructExpr&>(e);auto&s=structure(x.name,e.line,e.column);if(x.fields.size()!=s.fields.size())fail("wrong struct field count",e.line,e.column);for(std::size_t i=0;i<s.fields.size();++i){if(x.fields[i].first!=s.fields[i].first)fail("struct fields must be in declaration order",e.line,e.column);auto a=infer(*x.fields[i].second,vars);if(!compatible(*x.fields[i].second,a,s.fields[i].second))fail("struct field type mismatch",e.line,e.column);}return Type::structure(x.name,s.fields);}
            case Expr::Kind::Field:{auto&x=static_cast<const FieldExpr&>(e);auto t=infer(*x.base,vars);if(t.kind!=TypeKind::Struct)fail("field access requires struct",e.line,e.column);for(auto&f:t.fields)if(f.first==x.field)return f.second;const auto&s=structure(t.name,e.line,e.column);for(auto&f:s.fields)if(f.first==x.field)return f.second;fail("unknown struct field",e.line,e.column);}
            case Expr::Kind::Index:{auto&x=static_cast<const IndexExpr&>(e);auto t=infer(*x.base,vars);if(t.kind!=TypeKind::Array&&t.kind!=TypeKind::DynamicArray)fail("indexing requires an array",e.line,e.column);Type index=infer(*x.index,vars);if(index.kind!=TypeKind::I32&&index.kind!=TypeKind::I64)fail("array index must be an integer",e.line,e.column);return *t.element;}
        }fail("unsupported expression",e.line,e.column);
    }
    bool block(const std::vector<StatementPtr>& ss,std::unordered_map<std::string,Type>& vars,const Type& ret)const{bool r=false;for(const auto&sp:ss){const bool was_terminated=r;switch(sp->kind){case Statement::Kind::Let:{auto&x=static_cast<const LetStatement&>(*sp);if(vars.count(x.name))fail("duplicate local",x.line,x.column);auto a=infer(*x.value,vars);if(x.declared&&!compatible(*x.value,a,*x.declared))fail("declared type does not match initializer",x.line,x.column);vars[x.name]=x.declared.value_or(a);break;}case Statement::Kind::Assignment:{auto&x=static_cast<const AssignmentStatement&>(*sp);auto i=vars.find(x.name);if(i==vars.end())fail("unknown value '"+x.name+"'",x.line,x.column);auto a=infer(*x.value,vars);if(!compatible(*x.value,a,i->second))fail("assignment type does not match target",x.line,x.column);break;}case Statement::Kind::Return:{auto&x=static_cast<const ReturnStatement&>(*sp);if(ret.kind==TypeKind::Void){if(x.value)fail("void function cannot return value",x.line,x.column);}else{if(!x.value)fail("missing return value",x.line,x.column);auto a=infer(*x.value,vars);if(!compatible(*x.value,a,ret))fail("return type mismatch",x.line,x.column);}r=true;break;}case Statement::Kind::If:{auto&x=static_cast<const IfStatement&>(*sp);if(infer(*x.condition,vars).kind!=TypeKind::Bool)fail("if condition must be bool",x.line,x.column);auto a=vars,b=vars;bool ar=block(x.then_body,a,ret),br=!x.else_body.empty()&&block(x.else_body,b,ret);r=ar&&br;break;}case Statement::Kind::While:{auto&x=static_cast<const WhileStatement&>(*sp);if(infer(*x.condition,vars).kind!=TypeKind::Bool)fail("while condition must be bool",x.line,x.column);auto a=vars;block(x.body,a,ret);break;}case Statement::Kind::Expression:infer(*static_cast<const ExpressionStatement&>(*sp).expression,vars);break;}if(was_terminated)r=true;}return r;}
    void validateFunction(const Function& f)const{std::unordered_map<std::string,Type>v;for(auto&p:f.parameters){if(v.count(p.name))fail("duplicate parameter",f.line,1);v[p.name]=p.type;}if(f.return_type.kind!=TypeKind::Void&&!block(f.body,v,f.return_type))fail("function does not return on every path",f.line,1);}
    std::unordered_map<std::string,const StructDecl*>structs_;std::unordered_map<std::string,const Function*>functions_;
};

class LLVMEmitter final {
public:
    LLVMEmitter(const Program& p,std::string target):program_(p),target_(std::move(target)){for(const auto&f:p.functions)functions_[f.name]=&f;for(const auto&s:p.structs)structs_[s.name]=&s;}
    std::string emit(){collectStrings();std::ostringstream o;o<<"; Holy Fitra Stage-0 aggregate bootstrap module "<<program_.module<<"\n; target: "<<target_<<"\n";if(target_.rfind("aarch64",0)==0)o<<"; ABI: AAPCS64\n; vector capability: NEON when available\n";o<<"target triple = \""<<target_<<"\"\n\n";for(const auto&s:program_.structs){o<<"%struct."<<s.name<<" = type { ";for(std::size_t i=0;i<s.fields.size();++i){if(i)o<<", ";o<<s.fields[i].second.llvm();}o<<" }\n";}if(!program_.structs.empty())o<<"\n";for(const auto&g:strings_)o<<"@.str."<<g.second<<" = private unnamed_addr constant ["<<g.first.size()+1<<" x i8] c\""<<escape(g.first)<<"\\00\"\n";if(!strings_.empty())o<<"\n";for(const auto&f:builtinFunctions()){o<<"declare "<<f.return_type.llvm()<<" @"<<f.name<<"(";for(std::size_t i=0;i<f.parameters.size();++i){if(i)o<<", ";o<<f.parameters[i].type.llvm();}o<<")\n";}if(!builtinFunctions().empty())o<<"\n";for(const auto&f:program_.functions){emitFunction(f,o);o<<"\n";}return o.str();}
private:
    struct Local{Type type;std::string addr;};
    const Function& function(const std::string& name) const { auto i=functions_.find(name); if(i!=functions_.end()) return *i->second; if(const Function* b=findBuiltin(name)) return *b; fail("unknown function '"+name+"'"); }
    std::string tmp(){return "%t"+std::to_string(temp_++);}std::string label(const std::string&p){return p+std::to_string(label_++);}static std::string escape(const std::string&s){std::ostringstream o;for(unsigned char c:s){if(c=='\\')o<<"\\5C";else if(c=='"')o<<"\\22";else if(c=='\n')o<<"\\0A";else if(c<32||c>126){const char*hex="0123456789ABCDEF";o<<"\\"<<hex[c>>4]<<hex[c&15];}else o<<c;}return o.str();}
    void collectStrings(){for(const auto&f:program_.functions)collectBlock(f.body);}void collectBlock(const std::vector<StatementPtr>&ss){for(const auto&sp:ss){if(sp->kind==Statement::Kind::Let)collectExpr(*static_cast<const LetStatement&>(*sp).value);else if(sp->kind==Statement::Kind::Return&&static_cast<const ReturnStatement&>(*sp).value)collectExpr(*static_cast<const ReturnStatement&>(*sp).value);else if(sp->kind==Statement::Kind::Expression)collectExpr(*static_cast<const ExpressionStatement&>(*sp).expression);else if(sp->kind==Statement::Kind::If){auto&x=static_cast<const IfStatement&>(*sp);collectExpr(*x.condition);collectBlock(x.then_body);collectBlock(x.else_body);}else if(sp->kind==Statement::Kind::While){auto&x=static_cast<const WhileStatement&>(*sp);collectExpr(*x.condition);collectBlock(x.body);}}}void collectExpr(const Expr&e){if(e.kind==Expr::Kind::String){auto&s=static_cast<const StringExpr&>(e).value;if(!strings_.count(s))strings_[s]=strings_.size();}else if(e.kind==Expr::Kind::Unary)collectExpr(*static_cast<const UnaryExpr&>(e).operand);else if(e.kind==Expr::Kind::Binary){auto&x=static_cast<const BinaryExpr&>(e);collectExpr(*x.left);collectExpr(*x.right);}else if(e.kind==Expr::Kind::Call){for(auto&x:static_cast<const CallExpr&>(e).arguments)collectExpr(*x);}else if(e.kind==Expr::Kind::Array){for(auto&x:static_cast<const ArrayExpr&>(e).elements)collectExpr(*x);}else if(e.kind==Expr::Kind::Struct){for(auto&x:static_cast<const StructExpr&>(e).fields)collectExpr(*x.second);}else if(e.kind==Expr::Kind::Field)collectExpr(*static_cast<const FieldExpr&>(e).base);else if(e.kind==Expr::Kind::Index){auto&x=static_cast<const IndexExpr&>(e);collectExpr(*x.base);collectExpr(*x.index);}}
    Type localType(const Expr&e)const{if(e.kind==Expr::Kind::Integer)return Type::scalar(TypeKind::I32);if(e.kind==Expr::Kind::Boolean)return Type::scalar(TypeKind::Bool);if(e.kind==Expr::Kind::String)return Type::scalar(TypeKind::String);if(e.kind==Expr::Kind::Array){auto&x=static_cast<const ArrayExpr&>(e);return Type::array(x.elements.size(),localType(*x.elements[0]));}if(e.kind==Expr::Kind::Struct)return Type::structure(static_cast<const StructExpr&>(e).name);if(e.kind==Expr::Kind::Call)return function(static_cast<const CallExpr&>(e).name).return_type;if(e.kind==Expr::Kind::Name)return locals_.at(static_cast<const NameExpr&>(e).name).type;if(e.kind==Expr::Kind::Field){auto&x=static_cast<const FieldExpr&>(e);Type b=localType(*x.base);auto&s=*structs_.at(b.name);for(auto&f:s.fields)if(f.first==x.field)return f.second;}if(e.kind==Expr::Kind::Index)return *localType(*static_cast<const IndexExpr&>(e).base).element;return Type::scalar(TypeKind::I32);}
    std::pair<std::string,Type> expr(const Expr&e,std::ostringstream&o,std::optional<Type> expected=std::nullopt){
        if(e.kind==Expr::Kind::Integer){return {std::to_string(static_cast<const IntegerExpr&>(e).value),expected.value_or(Type::scalar(TypeKind::I32))};}
        if(e.kind==Expr::Kind::Boolean){return {static_cast<const BooleanExpr&>(e).value?"1":"0",expected.value_or(Type::scalar(TypeKind::Bool))
};}
        if(e.kind==Expr::Kind::String){auto&s=static_cast<const StringExpr&>(e).value;auto id=strings_.at(s);auto r=tmp();o<<"  "<<r<<" = getelementptr inbounds ["<<s.size()+1<<" x i8], ptr @.str."<<id<<", i64 0, i64 0\n";return {r,Type::scalar(TypeKind::String)};}
        if(e.kind==Expr::Kind::Name){auto&n=static_cast<const NameExpr&>(e).name;auto&l=locals_.at(n);auto r=tmp();o<<"  "<<r<<" = load "<<l.type.llvm()<<", ptr "<<l.addr<<"\n";return {r,l.type};}
        if(e.kind==Expr::Kind::Unary){auto&x=static_cast<const UnaryExpr&>(e);auto a=expr(*x.operand,o);auto r=tmp();if(x.op=="-")o<<"  "<<r<<" = sub "<<a.second.llvm()<<" 0, "<<a.first<<"\n";else o<<"  "<<r<<" = xor i1 "<<a.first<<", 1\n";return {r,a.second};}
        if(e.kind==Expr::Kind::Binary){
            auto&x=static_cast<const BinaryExpr&>(e);
            if(x.op=="&&"||x.op=="||"){
                auto a=expr(*x.left,o);
                auto rhs=label("bool_rhs"),shortc=label("bool_short"),merge=label("bool_merge"),r=tmp();
                if(x.op=="&&")o<<"  br i1 "<<a.first<<", label %"<<rhs<<", label %"<<shortc<<"\n";
                else o<<"  br i1 "<<a.first<<", label %"<<shortc<<", label %"<<rhs<<"\n";
                o<<rhs<<":\n";
                auto b=expr(*x.right,o,Type::scalar(TypeKind::Bool));
                o<<"  br label %"<<merge<<"\n";
                o<<shortc<<":\n";
                o<<"  br label %"<<merge<<"\n";
                o<<merge<<":\n";
                o<<"  "<<r<<" = phi i1 [ "<<b.first<<", %"<<rhs<<" ], [ "<<(x.op=="&&"?"0":"1")<<", %"<<shortc<<" ]\n";
                return {r,Type::scalar(TypeKind::Bool)};
            }
            auto a=expr(*x.left,o),b=expr(*x.right,o,a.second);auto r=tmp();
            if(x.op=="+"||x.op=="-"||x.op=="*"||x.op=="/")o<<"  "<<r<<" = "<<(x.op=="+"?"add":x.op=="-"?"sub":x.op=="*"?"mul":"sdiv")<<" "<<a.second.llvm()<<" "<<a.first<<", "<<b.first<<"\n";
            else{o<<"  "<<r<<" = icmp "<<std::map<std::string,std::string>{{"==","eq"},{"!=","ne"},{"<","slt"},{"<=","sle"},{">","sgt"},{">=","sge"}}.at(x.op)<<" "<<a.second.llvm()<<" "<<a.first<<", "<<b.first<<"\n";return {r,Type::scalar(TypeKind::Bool)};}
            return {r,a.second};
        }
        if(e.kind==Expr::Kind::Call){auto&x=static_cast<const CallExpr&>(e);const auto&f=function(x.name);std::vector<std::pair<std::string,Type>>a;for(std::size_t i=0;i<x.arguments.size();++i)a.push_back(expr(*x.arguments[i],o,f.parameters[i].type));std::ostringstream args;for(std::size_t i=0;i<a.size();++i){if(i)args<<", ";args<<f.parameters[i].type.llvm()<<" "<<a[i].first;}if(f.return_type.kind==TypeKind::Void){o<<"  call void @"<<f.name<<"("<<args.str()<<")\n";return {"",f.return_type};}auto r=tmp();o<<"  "<<r<<" = call "<<f.return_type.llvm()<<" @"<<f.name<<"("<<args.str()<<")\n";return {r,f.return_type};}
        if(e.kind==Expr::Kind::Array||e.kind==Expr::Kind::Struct){return {aggregate(e,expected.value_or(localType(e)),o),expected.value_or(localType(e))};}
        if(e.kind==Expr::Kind::Index){auto&x=static_cast<const IndexExpr&>(e);Type base=localType(*x.base);if(base.kind==TypeKind::DynamicArray&&base.element->kind==TypeKind::I32){auto a=expr(*x.base,o);auto i=expr(*x.index,o,Type::scalar(TypeKind::I64));auto r=tmp();o<<"  "<<r<<" = call i32 @hf_dyn_i32_get(ptr "<<a.first<<", i64 "<<i.first<<")\n";return {r,Type::scalar(TypeKind::I32)};}}
        if(e.kind==Expr::Kind::Field||e.kind==Expr::Kind::Index){auto a=address(e,o);auto r=tmp();Type t=localType(e);o<<"  "<<r<<" = load "<<t.llvm()<<", ptr "<<a.first<<"\n";return {r,t};}
        fail("unsupported aggregate expression",e.line,e.column);
    }
    std::pair<std::string,Type> address(const Expr&e,std::ostringstream&o){
        if(e.kind==Expr::Kind::Name){auto&l=locals_.at(static_cast<const NameExpr&>(e).name);return {l.addr,l.type};}
        if(e.kind==Expr::Kind::Field){auto&x=static_cast<const FieldExpr&>(e);auto b=address(*x.base,o);const StructDecl&s=*structs_.at(b.second.name);std::size_t index=0;Type field;for(std::size_t i=0;i<s.fields.size();++i)if(s.fields[i].first==x.field){index=i;field=s.fields[i].second;break;}auto r=tmp();o<<"  "<<r<<" = getelementptr inbounds "<<b.second.llvm()<<", ptr "<<b.first<<", i64 0, i32 "<<index<<"\n";return {r,field};}
        if(e.kind==Expr::Kind::Index){auto&x=static_cast<const IndexExpr&>(e);auto b=address(*x.base,o);auto i=expr(*x.index,o);auto r=tmp();o<<"  "<<r<<" = getelementptr inbounds "<<b.second.llvm()<<", ptr "<<b.first<<", i64 0, i64 "<<i.first<<"\n";return {r,*b.second.element};}
        fail("expression is not addressable",e.line,e.column);
    }
    std::string aggregate(const Expr&e,const Type&t,std::ostringstream&o){if(e.kind==Expr::Kind::Array){auto&x=static_cast<const ArrayExpr&>(e);std::ostringstream v;v<<"[";for(std::size_t i=0;i<x.elements.size();++i){if(i)v<<", ";auto a=expr(*x.elements[i],o,*t.element);v<<t.element->llvm()<<" "<<a.first;}v<<"]";return v.str();}auto&x=static_cast<const StructExpr&>(e);const StructDecl&s=*structs_.at(x.name);std::ostringstream v;v<<"{";for(std::size_t i=0;i<x.fields.size();++i){if(i)v<<", ";auto a=expr(*x.fields[i].second,o,s.fields[i].second);v<<s.fields[i].second.llvm()<<" "<<a.first;}v<<"}";return v.str();}
    void collect(const std::vector<StatementPtr>&ss,std::vector<std::pair<std::string,Type>>&ls,std::unordered_map<std::string,Type>&known){for(const auto&sp:ss){if(sp->kind==Statement::Kind::Let){auto&x=static_cast<const LetStatement&>(*sp);Type t=x.declared.value_or(localType(*x.value));ls.push_back({x.name,t});known[x.name]=t;locals_[x.name]={t,""};}else if(sp->kind==Statement::Kind::If){auto&x=static_cast<const IfStatement&>(*sp);collect(x.then_body,ls,known);collect(x.else_body,ls,known);}else if(sp->kind==Statement::Kind::While){collect(static_cast<const WhileStatement&>(*sp).body,ls,known);}}}
    bool block(const std::vector<StatementPtr>&ss,std::ostringstream&o,const Type&ret){bool term=false;for(const auto&sp:ss){if(term)break;if(sp->kind==Statement::Kind::Let){auto&x=static_cast<const LetStatement&>(*sp);auto v=expr(*x.value,o,x.declared);o<<"  store "<<v.second.llvm()<<" "<<v.first<<", ptr "<<locals_.at(x.name).addr<<"\n";}else if(sp->kind==Statement::Kind::Assignment){auto&x=static_cast<const AssignmentStatement&>(*sp);auto v=expr(*x.value,o,locals_.at(x.name).type);o<<"  store "<<v.second.llvm()<<" "<<v.first<<", ptr "<<locals_.at(x.name).addr<<"\n";}else if(sp->kind==Statement::Kind::Return){auto&x=static_cast<const ReturnStatement&>(*sp);if(!x.value)o<<"  ret void\n";else{auto v=expr(*x.value,o,ret);o<<"  ret "<<v.second.llvm()<<" "<<v.first<<"\n";}term=true;}else if(sp->kind==Statement::Kind::Expression)expr(*static_cast<const ExpressionStatement&>(*sp).expression,o);else if(sp->kind==Statement::Kind::If){auto&x=static_cast<const IfStatement&>(*sp);auto c=expr(*x.condition,o);auto a=label("if_then"),b=label("if_else"),m=label("if_merge");o<<"  br i1 "<<c.first<<", label %"<<a<<", label %"<<b<<"\n"<<a<<":\n";bool ar=block(x.then_body,o,ret);if(!ar)o<<"  br label %"<<m<<"\n";o<<b<<":\n";bool br=x.else_body.empty()?false:block(x.else_body,o,ret);if(!br)o<<"  br label %"<<m<<"\n";o<<m<<":\n";term=ar&&br;if(term)o<<"  unreachable\n";}else if(sp->kind==Statement::Kind::While){auto&x=static_cast<const WhileStatement&>(*sp);auto h=label("while_head"),b=label("while_body"),z=label("while_exit");o<<"  br label %"<<h<<"\n"<<h<<":\n";auto c=expr(*x.condition,o);o<<"  br i1 "<<c.first<<", label %"<<b<<", label %"<<z<<"\n"<<b<<":\n";bool bt=block(x.body,o,ret);if(!bt)o<<"  br label %"<<h<<"\n";o<<z<<":\n";}}return term;}
    void emitFunction(const Function&f,std::ostringstream&o){temp_=label_=0;locals_.clear();std::vector<std::pair<std::string,Type>>ls;std::unordered_map<std::string,Type>known;for(auto&p:f.parameters){ls.push_back({p.name,p.type});known[p.name]=p.type;locals_[p.name]={p.type,""};}collect(f.body,ls,known);for(auto&l:ls)locals_[l.first]={l.second,"%"+l.first+".addr"};o<<"; function: "<<f.name<<"\ndefine "<<f.return_type.llvm()<<" @"<<f.name<<"(";for(std::size_t i=0;i<f.parameters.size();++i){if(i)o<<", ";o<<f.parameters[i].type.llvm()<<" %"<<f.parameters[i].name;}o<<") {\nentry:\n";for(auto&l:ls)o<<"  "<<locals_[l.first].addr<<" = alloca "<<l.second.llvm()<<"\n";for(auto&p:f.parameters)o<<"  store "<<p.type.llvm()<<" %"<<p.name<<", ptr "<<locals_[p.name].addr<<"\n";bool term=block(f.body,o,f.return_type);if(!term&&f.return_type.kind==TypeKind::Void)o<<"  ret void\n";else if(!term)fail("function has no terminating return",f.line,1);o<<"}\n";}
    const Program&program_;std::string target_;std::unordered_map<std::string,const Function*>functions_;std::unordered_map<std::string,const StructDecl*>structs_;std::map<std::string,std::size_t>strings_;std::unordered_map<std::string,Local>locals_;int temp_=0,label_=0;
};

static std::string readFile(const std::string&path){
    std::ifstream in(path,std::ios::binary);
    if(!in)fail("cannot open input file '"+path+"'");
    in.seekg(0,std::ios::end);
    const std::streamoff size=in.tellg();
    if(size<0 || static_cast<std::uint64_t>(size)>kMaxSourceBytes) fail("source exceeds the 8 MiB limit");
    in.seekg(0,std::ios::beg);
    std::string source(static_cast<std::size_t>(size), static_cast<char>(0));
    if(size>0 && !in.read(source.data(),size)) fail("cannot read input file '"+path+"'");
    return source;
}
static void writeFile(const std::string&path,const std::string&text){std::ofstream out(path,std::ios::binary|std::ios::trunc);if(!out)fail("cannot open output file '"+path+"'");out<<text;}
static void usage(const char*p){std::cerr<<"usage: "<<p<<" [--target=TRIPLE] INPUT.hf [-o OUTPUT.ll]\n";}
static constexpr const char *kVersion = "1.0.0-seed";

static std::string diagnosticCode(const Diagnostic& diagnostic) {
    const std::string message = diagnostic.what();
    if (message.find("expected") != std::string::npos || message.find("unexpected") != std::string::npos) return "HF1001";
    if (message.find("unknown") != std::string::npos || message.find("duplicate") != std::string::npos) return "HF2001";
    if (message.find("type") != std::string::npos || message.find("operand") != std::string::npos || message.find("return") != std::string::npos) return "HF3001";
    if (message.find("array") != std::string::npos || message.find("index") != std::string::npos) return "HF4001";
    if (message.find("function") != std::string::npos || message.find("argument") != std::string::npos) return "HF5001";
    return diagnostic.code;
}

class DiagnosticReporter final {
public:
    static void render(std::ostream& output, const Diagnostic& diagnostic, const std::string& path, const std::string& source) {
        const std::string code = diagnosticCode(diagnostic);
        output << path << ":" << diagnostic.span.begin.line << ":" << diagnostic.span.begin.column
               << ": error[" << code << "]: " << diagnostic.what() << "\n";
        if (diagnostic.span.valid()) renderSpan(output, diagnostic.span, source, "  ");
        for (const auto& note : diagnostic.notes) {
            output << "note: " << note.message << "\n";
            if (note.span.valid()) renderSpan(output, note.span, source, "  ");
        }
    }
private:
    static std::vector<std::string> lines(const std::string& source) {
        std::vector<std::string> result;
        std::string current;
        for (char c : source) { if (c == '\n') { result.push_back(current); current.clear(); } else current.push_back(c); }
        result.push_back(current);
        return result;
    }
    static void renderSpan(std::ostream& output, const SourceSpan& span, const std::string& source, const std::string& indent) {
        const auto source_lines = lines(source);
        if (span.begin.line <= 0 || static_cast<std::size_t>(span.begin.line) > source_lines.size()) return;
        const std::string& source_line = source_lines[static_cast<std::size_t>(span.begin.line - 1)];
        output << indent << span.begin.line << " | " << source_line << "\n";
        const int column = span.begin.column > 0 ? span.begin.column : 1;
        int width = 1;
        if (span.end.line == span.begin.line && span.end.column > span.begin.column) width = span.end.column - span.begin.column;
        output << indent << "  | " << std::string(static_cast<std::size_t>(column - 1), ' ') << "^";
        if (width > 1) output << std::string(static_cast<std::size_t>(width - 1), '~');
        output << "\n";
    }
};

} // namespace hf0

int main(int argc,char**argv){using namespace hf0;std::string input,source;try{if(argc<2){usage(argv[0]);return 2;}std::string output,target="x86_64-pc-linux-gnu";for(int i=1;i<argc;++i){std::string a=argv[i];if(a=="--help"||a=="-h"){usage(argv[0]);return 0;}if(a=="--version"){std::cout<<kVersion<<static_cast<char>(10);return 0;}if(a.rfind("--target=",0)==0){target=a.substr(9);continue;}if(a=="--target"){if(++i>=argc)fail("--target requires a value");target=argv[i];continue;}if(a=="-o"||a=="--output"){if(++i>=argc)fail("-o requires a path");output=argv[i];continue;}if(!a.empty()&&a[0]=='-')fail("unknown option '"+a+"'");if(!input.empty())fail("multiple input files are unsupported");input=a;}if(input.empty()){usage(argv[0]);return 2;}source=readFile(input);Program p=Parser(Lexer(source).run()).parse();Validator().run(p);std::string llvm=LLVMEmitter(p,target).emit();if(output.empty())std::cout<<llvm;else{writeFile(output,llvm);std::cerr<<"holyfitra-bootstrap: wrote "<<output<<"\n";}return 0;}catch(const Diagnostic&d){DiagnosticReporter::render(std::cerr,d,input.empty()?"<command line>":input,source);return 1;}catch(const std::exception&e){std::cerr<<"holyfitra-bootstrap: internal error: "<<e.what()<<"\n";return 1;}}
