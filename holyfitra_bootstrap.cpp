// Holy Fitra Stage-0 bootstrap compiler.
//
// This deliberately small compiler has no Python dependency.  It accepts the
// bootstrap scalar subset of Holy Fitra and emits textual LLVM IR.  Clang or
// LLVM can then lower that IR to host or AArch64 objects/executables.
//
// Supported source subset:
//   module name
//   fn name(a: i32, b: i64) -> i32 { ... }
//   types: i32, i64, bool, void
//   let/var, return, if/else, while, expression statements
//   integer/boolean literals, names, calls, arithmetic, comparisons, &&, ||
//   unary - and !
//
// Deliberate bootstrap constraints:
//   * no imports, tensors, effects, tasks, hybrids, pointers, or generics;
//   * each function has one lexical local scope; shadowing is rejected;
//   * assignments are not part of this first seed subset;
//   * while loops are supported for compiler implementation code, but the
//     validator does not treat a while loop as guaranteeing a return.
//
// Build:
//   clang++ -std=c++17 -O2 -Wall -Wextra -pedantic holyfitra_bootstrap.cpp \
//       -o holyfitra_bootstrap
//
// Emit LLVM:
//   ./holyfitra_bootstrap --target=x86_64-pc-linux-gnu input.hf -o input.ll
//   ./holyfitra_bootstrap --target=aarch64-linux-android21 input.hf -o input.ll
//
// Build native output after emission:
//   clang input.ll -O2 -o input
//   clang --target=aarch64-linux-android21 -c input.ll -o input.aarch64.o

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace hf0 {

struct Diagnostic final : std::runtime_error {
    int line;
    int column;
    Diagnostic(std::string message, int line = 0, int column = 0)
        : std::runtime_error(std::move(message)), line(line), column(column) {}
};

[[noreturn]] static void fail(const std::string& message, int line = 0, int column = 0) {
    throw Diagnostic(message, line, column);
}

static std::string location(int line, int column) {
    if (line <= 0) return {};
    return " at " + std::to_string(line) + ":" + std::to_string(column);
}

enum class TokenKind {
    Eof,
    Identifier,
    Integer,
    Arrow,
    Operator,
    Punctuation,
};

struct Token final {
    TokenKind kind;
    std::string text;
    int line;
    int column;
};

class Lexer final {
public:
    explicit Lexer(std::string source) : source_(std::move(source)) {}

    std::vector<Token> run() {
        std::vector<Token> tokens;
        while (position_ < source_.size()) {
            char c = source_[position_];
            if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
                advanceChar();
                continue;
            }
            if (c == '/' && peek(1) == '/') {
                skipLineComment();
                continue;
            }
            if (c == '#') {
                skipLineComment();
                continue;
            }
            const int line = line_;
            const int column = column_;
            if (isIdentifierStart(c)) {
                std::string value;
                while (position_ < source_.size() && isIdentifierContinue(source_[position_])) {
                    value.push_back(source_[position_]);
                    advanceChar();
                }
                tokens.push_back({TokenKind::Identifier, std::move(value), line, column});
                continue;
            }
            if (c >= '0' && c <= '9') {
                std::string value;
                while (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') {
                    value.push_back(source_[position_]);
                    advanceChar();
                }
                tokens.push_back({TokenKind::Integer, std::move(value), line, column});
                continue;
            }
            if (c == '-' && peek(1) == '>') {
                advanceChar();
                advanceChar();
                tokens.push_back({TokenKind::Arrow, "->", line, column});
                continue;
            }
            const std::string two = std::string() + c + peek(1);
            if (two == "==" || two == "!=" || two == "<=" || two == ">=" || two == "&&" || two == "||") {
                advanceChar();
                advanceChar();
                tokens.push_back({TokenKind::Operator, two, line, column});
                continue;
            }
            if (std::string("+-*/=<>!").find(c) != std::string::npos) {
                advanceChar();
                tokens.push_back({TokenKind::Operator, std::string(1, c), line, column});
                continue;
            }
            if (std::string("{}(),:;").find(c) != std::string::npos) {
                advanceChar();
                tokens.push_back({TokenKind::Punctuation, std::string(1, c), line, column});
                continue;
            }
            fail(std::string("unexpected character '") + c + "'" + location(line, column), line, column);
        }
        tokens.push_back({TokenKind::Eof, "", line_, column_});
        return tokens;
    }

private:
    static bool isIdentifierStart(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
    }

    static bool isIdentifierContinue(char c) {
        return isIdentifierStart(c) || (c >= '0' && c <= '9');
    }

    char peek(std::size_t offset) const {
        const std::size_t index = position_ + offset;
        return index < source_.size() ? source_[index] : '\0';
    }

    void advanceChar() {
        if (position_ >= source_.size()) return;
        if (source_[position_] == '\n') {
            ++line_;
            column_ = 1;
        } else {
            ++column_;
        }
        ++position_;
    }

    void skipLineComment() {
        while (position_ < source_.size() && source_[position_] != '\n') advanceChar();
    }

    std::string source_;
    std::size_t position_ = 0;
    int line_ = 1;
    int column_ = 1;
};

enum class TypeKind { I32, I64, Bool, Void };

struct Type final {
    TypeKind kind;
    std::string name() const {
        switch (kind) {
            case TypeKind::I32: return "i32";
            case TypeKind::I64: return "i64";
            case TypeKind::Bool: return "bool";
            case TypeKind::Void: return "void";
        }
        return "unknown";
    }
    std::string llvm() const {
        switch (kind) {
            case TypeKind::I32: return "i32";
            case TypeKind::I64: return "i64";
            case TypeKind::Bool: return "i1";
            case TypeKind::Void: return "void";
        }
        return "void";
    }
    bool operator==(const Type& other) const { return kind == other.kind; }
    bool operator!=(const Type& other) const { return !(*this == other); }
};

struct Expr;
struct Statement;
using ExprPtr = std::unique_ptr<Expr>;
using StatementPtr = std::unique_ptr<Statement>;

struct Expr {
    enum class Kind { Integer, Boolean, Name, Unary, Binary, Call };
    explicit Expr(Kind kind, int line, int column) : kind(kind), line(line), column(column) {}
    virtual ~Expr() = default;
    Kind kind;
    int line;
    int column;
};

struct IntegerExpr final : Expr {
    IntegerExpr(std::int64_t value, int line, int column) : Expr(Kind::Integer, line, column), value(value) {}
    std::int64_t value;
};

struct BooleanExpr final : Expr {
    BooleanExpr(bool value, int line, int column) : Expr(Kind::Boolean, line, column), value(value) {}
    bool value;
};

struct NameExpr final : Expr {
    NameExpr(std::string name, int line, int column) : Expr(Kind::Name, line, column), name(std::move(name)) {}
    std::string name;
};

struct UnaryExpr final : Expr {
    UnaryExpr(std::string op, ExprPtr operand, int line, int column)
        : Expr(Kind::Unary, line, column), op(std::move(op)), operand(std::move(operand)) {}
    std::string op;
    ExprPtr operand;
};

struct BinaryExpr final : Expr {
    BinaryExpr(std::string op, ExprPtr left, ExprPtr right, int line, int column)
        : Expr(Kind::Binary, line, column), op(std::move(op)), left(std::move(left)), right(std::move(right)) {}
    std::string op;
    ExprPtr left;
    ExprPtr right;
};

struct CallExpr final : Expr {
    CallExpr(std::string name, std::vector<ExprPtr> arguments, int line, int column)
        : Expr(Kind::Call, line, column), name(std::move(name)), arguments(std::move(arguments)) {}
    std::string name;
    std::vector<ExprPtr> arguments;
};

struct Statement {
    enum class Kind { Let, Return, If, While, Expression };
    explicit Statement(Kind kind, int line, int column) : kind(kind), line(line), column(column) {}
    virtual ~Statement() = default;
    Kind kind;
    int line;
    int column;
};

struct LetStatement final : Statement {
    LetStatement(std::string name, std::optional<Type> declared, ExprPtr value, bool mutable_value, int line, int column)
        : Statement(Kind::Let, line, column), name(std::move(name)), declared(std::move(declared)), value(std::move(value)), mutable_value(mutable_value) {}
    std::string name;
    std::optional<Type> declared;
    ExprPtr value;
    bool mutable_value;
};

struct ReturnStatement final : Statement {
    ReturnStatement(ExprPtr value, int line, int column) : Statement(Kind::Return, line, column), value(std::move(value)) {}
    ExprPtr value;
};

struct IfStatement final : Statement {
    IfStatement(ExprPtr condition, std::vector<StatementPtr> then_body, std::vector<StatementPtr> else_body, int line, int column)
        : Statement(Kind::If, line, column), condition(std::move(condition)), then_body(std::move(then_body)), else_body(std::move(else_body)) {}
    ExprPtr condition;
    std::vector<StatementPtr> then_body;
    std::vector<StatementPtr> else_body;
};

struct WhileStatement final : Statement {
    WhileStatement(ExprPtr condition, std::vector<StatementPtr> body, int line, int column)
        : Statement(Kind::While, line, column), condition(std::move(condition)), body(std::move(body)) {}
    ExprPtr condition;
    std::vector<StatementPtr> body;
};

struct ExpressionStatement final : Statement {
    ExpressionStatement(ExprPtr expression, int line, int column)
        : Statement(Kind::Expression, line, column), expression(std::move(expression)) {}
    ExprPtr expression;
};

struct Parameter final {
    std::string name;
    Type type;
};

struct Function final {
    std::string name;
    std::vector<Parameter> parameters;
    Type return_type{TypeKind::Void};
    std::vector<StatementPtr> body;
    int line = 0;
};

struct Program final {
    std::string module = "anonymous";
    std::vector<Function> functions;
};

class Parser final {
public:
    explicit Parser(std::vector<Token> tokens) : tokens_(std::move(tokens)) {}

    Program parse() {
        Program program;
        if (acceptIdentifier("module")) {
            program.module = expect(TokenKind::Identifier, "module name").text;
        }
        while (!is(TokenKind::Eof)) {
            if (acceptIdentifier("fn")) {
                program.functions.push_back(parseFunction());
            } else {
                unexpected("top-level declaration");
            }
        }
        if (program.functions.empty()) fail("program must declare at least one function");
        return program;
    }

private:
    const Token& current() const { return tokens_.at(index_); }

    bool is(TokenKind kind) const { return current().kind == kind; }

    bool isText(TokenKind kind, const std::string& text) const {
        return current().kind == kind && current().text == text;
    }

    Token advance() {
        const Token token = current();
        if (index_ < tokens_.size() - 1) ++index_;
        return token;
    }

    bool accept(TokenKind kind, const std::string& text = {}) {
        if (current().kind == kind && (text.empty() || current().text == text)) {
            advance();
            return true;
        }
        return false;
    }

    bool acceptIdentifier(const std::string& text) { return accept(TokenKind::Identifier, text); }

    Token expect(TokenKind kind, const std::string& description) {
        if (!is(kind)) unexpected(description);
        return advance();
    }

    void expectText(TokenKind kind, const std::string& text) {
        if (!isText(kind, text)) unexpected("'" + text + "'");
        advance();
    }

    [[noreturn]] void unexpected(const std::string& expected) const {
        fail("expected " + expected + ", got '" + current().text + "'" + location(current().line, current().column), current().line, current().column);
    }

    Function parseFunction() {
        const Token name = expect(TokenKind::Identifier, "function name");
        expectText(TokenKind::Punctuation, "(");
        std::vector<Parameter> parameters;
        if (!accept(TokenKind::Punctuation, ")")) {
            while (true) {
                const Token parameter = expect(TokenKind::Identifier, "parameter name");
                expectText(TokenKind::Punctuation, ":");
                parameters.push_back({parameter.text, parseType()});
                if (accept(TokenKind::Punctuation, ")")) break;
                expectText(TokenKind::Punctuation, ",");
            }
        }
        expect(TokenKind::Arrow, "'->'");
        Type return_type = parseType();
        Function function{name.text, std::move(parameters), return_type, {}, name.line};
        function.body = parseBlock();
        return function;
    }

    Type parseType() {
        const Token type = expect(TokenKind::Identifier, "type");
        if (type.text == "i32") return {TypeKind::I32};
        if (type.text == "i64") return {TypeKind::I64};
        if (type.text == "bool") return {TypeKind::Bool};
        if (type.text == "void") return {TypeKind::Void};
        fail("unsupported bootstrap type '" + type.text + "'" + location(type.line, type.column), type.line, type.column);
    }

    std::vector<StatementPtr> parseBlock() {
        expectText(TokenKind::Punctuation, "{");
        std::vector<StatementPtr> body;
        while (!accept(TokenKind::Punctuation, "}")) {
            if (is(TokenKind::Eof)) unexpected("'}'");
            body.push_back(parseStatement());
        }
        return body;
    }

    StatementPtr parseStatement() {
        if (isText(TokenKind::Identifier, "let") || isText(TokenKind::Identifier, "var")) {
            const Token keyword = advance();
            const Token name = expect(TokenKind::Identifier, "local name");
            std::optional<Type> declared;
            if (accept(TokenKind::Punctuation, ":")) declared = parseType();
            expectText(TokenKind::Operator, "=");
            ExprPtr value = parseExpression();
            accept(TokenKind::Punctuation, ";");
            return std::make_unique<LetStatement>(name.text, declared, std::move(value), keyword.text == "var", name.line, name.column);
        }
        if (acceptIdentifier("return")) {
            const Token keyword = tokens_.at(index_ - 1);
            ExprPtr value;
            if (!isText(TokenKind::Punctuation, ";") && !isText(TokenKind::Punctuation, "}")) value = parseExpression();
            accept(TokenKind::Punctuation, ";");
            return std::make_unique<ReturnStatement>(std::move(value), keyword.line, keyword.column);
        }
        if (acceptIdentifier("if")) {
            const Token keyword = tokens_.at(index_ - 1);
            ExprPtr condition = parseExpression();
            std::vector<StatementPtr> then_body = parseBlock();
            std::vector<StatementPtr> else_body;
            if (acceptIdentifier("else")) else_body = parseBlock();
            return std::make_unique<IfStatement>(std::move(condition), std::move(then_body), std::move(else_body), keyword.line, keyword.column);
        }
        if (acceptIdentifier("while")) {
            const Token keyword = tokens_.at(index_ - 1);
            ExprPtr condition = parseExpression();
            std::vector<StatementPtr> body = parseBlock();
            return std::make_unique<WhileStatement>(std::move(condition), std::move(body), keyword.line, keyword.column);
        }
        const Token start = current();
        ExprPtr expression = parseExpression();
        accept(TokenKind::Punctuation, ";");
        return std::make_unique<ExpressionStatement>(std::move(expression), start.line, start.column);
    }

    ExprPtr parseExpression() { return parseLogicalOr(); }

    ExprPtr parseLogicalOr() {
        ExprPtr expression = parseLogicalAnd();
        while (isText(TokenKind::Operator, "||")) {
            const Token op = advance();
            expression = std::make_unique<BinaryExpr>(op.text, std::move(expression), parseLogicalAnd(), op.line, op.column);
        }
        return expression;
    }

    ExprPtr parseLogicalAnd() {
        ExprPtr expression = parseComparison();
        while (isText(TokenKind::Operator, "&&")) {
            const Token op = advance();
            expression = std::make_unique<BinaryExpr>(op.text, std::move(expression), parseComparison(), op.line, op.column);
        }
        return expression;
    }

    ExprPtr parseComparison() {
        ExprPtr expression = parseAdditive();
        while (is(TokenKind::Operator) && (current().text == "==" || current().text == "!=" || current().text == "<" || current().text == "<=" || current().text == ">" || current().text == ">=")) {
            const Token op = advance();
            expression = std::make_unique<BinaryExpr>(op.text, std::move(expression), parseAdditive(), op.line, op.column);
        }
        return expression;
    }

    ExprPtr parseAdditive() {
        ExprPtr expression = parseMultiplicative();
        while (is(TokenKind::Operator) && (current().text == "+" || current().text == "-")) {
            const Token op = advance();
            expression = std::make_unique<BinaryExpr>(op.text, std::move(expression), parseMultiplicative(), op.line, op.column);
        }
        return expression;
    }

    ExprPtr parseMultiplicative() {
        ExprPtr expression = parseUnary();
        while (is(TokenKind::Operator) && (current().text == "*" || current().text == "/")) {
            const Token op = advance();
            expression = std::make_unique<BinaryExpr>(op.text, std::move(expression), parseUnary(), op.line, op.column);
        }
        return expression;
    }

    ExprPtr parseUnary() {
        if (isText(TokenKind::Operator, "-") || isText(TokenKind::Operator, "!")) {
            const Token op = advance();
            return std::make_unique<UnaryExpr>(op.text, parseUnary(), op.line, op.column);
        }
        return parsePrimary();
    }

    ExprPtr parsePrimary() {
        if (is(TokenKind::Integer)) {
            const Token token = advance();
            try {
                std::size_t consumed = 0;
                const long long value = std::stoll(token.text, &consumed, 10);
                if (consumed != token.text.size()) throw std::invalid_argument("integer");
                return std::make_unique<IntegerExpr>(value, token.line, token.column);
            } catch (const std::exception&) {
                fail("invalid integer literal" + location(token.line, token.column), token.line, token.column);
            }
        }
        if (isText(TokenKind::Identifier, "true") || isText(TokenKind::Identifier, "false")) {
            const Token token = advance();
            return std::make_unique<BooleanExpr>(token.text == "true", token.line, token.column);
        }
        if (is(TokenKind::Identifier)) {
            const Token name = advance();
            if (!accept(TokenKind::Punctuation, "(")) return std::make_unique<NameExpr>(name.text, name.line, name.column);
            std::vector<ExprPtr> arguments;
            if (!accept(TokenKind::Punctuation, ")")) {
                while (true) {
                    arguments.push_back(parseExpression());
                    if (accept(TokenKind::Punctuation, ")")) break;
                    expectText(TokenKind::Punctuation, ",");
                }
            }
            return std::make_unique<CallExpr>(name.text, std::move(arguments), name.line, name.column);
        }
        if (accept(TokenKind::Punctuation, "(")) {
            ExprPtr expression = parseExpression();
            expectText(TokenKind::Punctuation, ")");
            return expression;
        }
        unexpected("expression");
    }

    std::vector<Token> tokens_;
    std::size_t index_ = 0;
};

class Validator final {
public:
    void run(const Program& program) {
        functions_.clear();
        for (const Function& function : program.functions) {
            if (functions_.find(function.name) != functions_.end()) fail("duplicate function '" + function.name + "'", function.line, 1);
            functions_.emplace(function.name, &function);
        }
        for (const Function& function : program.functions) validateFunction(function);
    }

private:
    static bool compatible(const Expr& expression, const Type& actual, const Type& expected) {
        return actual == expected || (expression.kind == Expr::Kind::Integer && actual.kind == TypeKind::I32 && expected.kind == TypeKind::I64);
    }

    Type infer(const Expr& expression, std::unordered_map<std::string, Type>& variables) const {
        switch (expression.kind) {
            case Expr::Kind::Integer:
                return {TypeKind::I32};
            case Expr::Kind::Boolean:
                return {TypeKind::Bool};
            case Expr::Kind::Name: {
                const auto& name = static_cast<const NameExpr&>(expression).name;
                const auto it = variables.find(name);
                if (it == variables.end()) fail("unknown value '" + name + "'", expression.line, expression.column);
                return it->second;
            }
            case Expr::Kind::Unary: {
                const auto& unary = static_cast<const UnaryExpr&>(expression);
                const Type operand = infer(*unary.operand, variables);
                if (unary.op == "-" && operand.kind != TypeKind::I32 && operand.kind != TypeKind::I64) fail("unary '-' requires an integer", expression.line, expression.column);
                if (unary.op == "!" && operand.kind != TypeKind::Bool) fail("unary '!' requires bool", expression.line, expression.column);
                return operand.kind == TypeKind::Bool ? Type{TypeKind::Bool} : operand;
            }
            case Expr::Kind::Binary: {
                const auto& binary = static_cast<const BinaryExpr&>(expression);
                const Type left = infer(*binary.left, variables);
                const Type right = infer(*binary.right, variables);
                if (left != right) fail("binary operands must have the same type", expression.line, expression.column);
                if (binary.op == "&&" || binary.op == "||") {
                    if (left.kind != TypeKind::Bool) fail("logical operators require bool", expression.line, expression.column);
                    return {TypeKind::Bool};
                }
                if (binary.op == "==" || binary.op == "!=" || binary.op == "<" || binary.op == "<=" || binary.op == ">" || binary.op == ">=") {
                    if (left.kind != TypeKind::I32 && left.kind != TypeKind::I64 && left.kind != TypeKind::Bool) fail("unsupported comparison type", expression.line, expression.column);
                    return {TypeKind::Bool};
                }
                if (left.kind != TypeKind::I32 && left.kind != TypeKind::I64) fail("arithmetic requires integers", expression.line, expression.column);
                return left;
            }
            case Expr::Kind::Call: {
                const auto& call = static_cast<const CallExpr&>(expression);
                const auto function_it = functions_.find(call.name);
                if (function_it == functions_.end()) fail("unknown function '" + call.name + "'", expression.line, expression.column);
                const Function& function = *function_it->second;
                if (call.arguments.size() != function.parameters.size()) fail("wrong argument count for '" + call.name + "'", expression.line, expression.column);
                for (std::size_t i = 0; i < call.arguments.size(); ++i) {
                    const Type actual = infer(*call.arguments[i], variables);
                    if (!compatible(*call.arguments[i], actual, function.parameters[i].type)) fail("argument type mismatch for '" + call.name + "'", expression.line, expression.column);
                }
                return function.return_type;
            }
        }
        fail("unsupported expression", expression.line, expression.column);
    }

    bool validateBlock(const std::vector<StatementPtr>& statements, std::unordered_map<std::string, Type>& variables, const Type& return_type) const {
        bool guaranteed_return = false;
        for (const auto& statement : statements) {
            if (guaranteed_return) break;
            switch (statement->kind) {
                case Statement::Kind::Let: {
                    const auto& let = static_cast<const LetStatement&>(*statement);
                    if (variables.find(let.name) != variables.end()) fail("local shadowing or duplicate local '" + let.name + "'", let.line, let.column);
                    const Type actual = infer(*let.value, variables);
                    if (let.declared.has_value() && !compatible(*let.value, actual, *let.declared)) fail("declared type does not match initializer", let.line, let.column);
                    variables.emplace(let.name, let.declared.value_or(actual));
                    break;
                }
                case Statement::Kind::Return: {
                    const auto& ret = static_cast<const ReturnStatement&>(*statement);
                    if (return_type.kind == TypeKind::Void) {
                        if (ret.value) fail("void function cannot return a value", ret.line, ret.column);
                    } else {
                        if (!ret.value) fail("non-void function must return a value", ret.line, ret.column);
                        const Type actual = infer(*ret.value, variables);
                        if (!compatible(*ret.value, actual, return_type)) fail("return type mismatch", ret.line, ret.column);
                    }
                    guaranteed_return = true;
                    break;
                }
                case Statement::Kind::If: {
                    const auto& conditional = static_cast<const IfStatement&>(*statement);
                    if (infer(*conditional.condition, variables).kind != TypeKind::Bool) fail("if condition must be bool", conditional.line, conditional.column);
                    auto then_variables = variables;
                    auto else_variables = variables;
                    const bool then_return = validateBlock(conditional.then_body, then_variables, return_type);
                    const bool else_return = !conditional.else_body.empty() && validateBlock(conditional.else_body, else_variables, return_type);
                    guaranteed_return = then_return && else_return;
                    break;
                }
                case Statement::Kind::While: {
                    const auto& loop = static_cast<const WhileStatement&>(*statement);
                    if (infer(*loop.condition, variables).kind != TypeKind::Bool) fail("while condition must be bool", loop.line, loop.column);
                    auto body_variables = variables;
                    validateBlock(loop.body, body_variables, return_type);
                    break;
                }
                case Statement::Kind::Expression: {
                    const Type expression_type = infer(*static_cast<const ExpressionStatement&>(*statement).expression, variables);
                    if (expression_type.kind != TypeKind::Void) {
                        // Expression statements may discard non-void values in the seed subset.
                    }
                    break;
                }
            }
        }
        return guaranteed_return;
    }

    void validateFunction(const Function& function) const {
        std::unordered_map<std::string, Type> variables;
        for (const Parameter& parameter : function.parameters) {
            if (variables.find(parameter.name) != variables.end()) fail("duplicate parameter '" + parameter.name + "'", function.line, 1);
            variables.emplace(parameter.name, parameter.type);
        }
        const bool guaranteed_return = validateBlock(function.body, variables, function.return_type);
        if (function.return_type.kind != TypeKind::Void && !guaranteed_return) fail("function '" + function.name + "' does not return on every path", function.line, 1);
    }

    std::unordered_map<std::string, const Function*> functions_;
};

class LLVMEmitter final {
public:
    explicit LLVMEmitter(const Program& program, std::string target) : program_(program), target_(std::move(target)) {
        for (const Function& function : program_.functions) functions_.emplace(function.name, &function);
    }

    std::string emit() {
        std::ostringstream out;
        out << "; Holy Fitra Stage-0 bootstrap module " << program_.module << "\n";
        out << "; target: " << target_ << "\n";
        if (target_.rfind("aarch64", 0) == 0) {
            out << "; ABI: AAPCS64\n";
            out << "; vector capability: NEON when available\n";
        }
        out << "target triple = \"" << target_ << "\"\n\n";
        for (const Function& function : program_.functions) {
            emitFunction(function, out);
            out << "\n";
        }
        return out.str();
    }

private:
    struct Local final {
        Type type;
        std::string address;
    };

    static std::string escapeName(const std::string& name) {
        std::string result;
        result.reserve(name.size() + 1);
        for (char c : name) result.push_back((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' ? c : '_');
        return result;
    }

    std::string temp() { return "%t" + std::to_string(temp_counter_++); }
    std::string label(const std::string& prefix) { return prefix + std::to_string(label_counter_++); }

    static std::string zeroValue(const Type& type) {
        return type.kind == TypeKind::Void ? "" : "0";
    }

    Type inferCollectionType(const Expr& expression, const std::unordered_map<std::string, Type>& known) const {
        if (expression.kind == Expr::Kind::Integer) return {TypeKind::I32};
        if (expression.kind == Expr::Kind::Boolean) return {TypeKind::Bool};
        if (expression.kind == Expr::Kind::Unary) return inferCollectionType(*static_cast<const UnaryExpr&>(expression).operand, known);
        if (expression.kind == Expr::Kind::Binary) return inferCollectionType(*static_cast<const BinaryExpr&>(expression).left, known);
        if (expression.kind == Expr::Kind::Call) return functions_.at(static_cast<const CallExpr&>(expression).name)->return_type;
        if (expression.kind == Expr::Kind::Name) {
            const auto& name = static_cast<const NameExpr&>(expression).name;
            const auto it = known.find(name);
            if (it != known.end()) return it->second;
        }
        return {TypeKind::I32};
    }

    void collectLocals(const std::vector<StatementPtr>& statements, std::vector<std::pair<std::string, Type>>& locals, std::unordered_map<std::string, Type>& known) {
        for (const auto& statement : statements) {
            switch (statement->kind) {
                case Statement::Kind::Let: {
                    const auto& let = static_cast<const LetStatement&>(*statement);
                    const Type type = let.declared.value_or(inferCollectionType(*let.value, known));
                    locals.emplace_back(let.name, type);
                    known.emplace(let.name, type);
                    break;
                }
                case Statement::Kind::If: {
                    const auto& conditional = static_cast<const IfStatement&>(*statement);
                    collectLocals(conditional.then_body, locals, known);
                    collectLocals(conditional.else_body, locals, known);
                    break;
                }
                case Statement::Kind::While:
                    collectLocals(static_cast<const WhileStatement&>(*statement).body, locals, known);
                    break;
                default:
                    break;
            }
        }
    }

    // The validator has already checked all local initializer types.  This
    // helper is retained as a conservative fallback for malformed ASTs.
    Type inferLocalType(const Expr& expression) const {
        if (expression.kind == Expr::Kind::Integer) return {TypeKind::I32};
        if (expression.kind == Expr::Kind::Boolean) return {TypeKind::Bool};
        if (expression.kind == Expr::Kind::Unary) return inferLocalType(*static_cast<const UnaryExpr&>(expression).operand);
        if (expression.kind == Expr::Kind::Binary) return inferLocalType(*static_cast<const BinaryExpr&>(expression).left);
        if (expression.kind == Expr::Kind::Call) {
            const auto& call = static_cast<const CallExpr&>(expression);
            return functions_.at(call.name)->return_type;
        }
        if (expression.kind == Expr::Kind::Name) {
            const auto& name = static_cast<const NameExpr&>(expression).name;
            const auto it = locals_.find(name);
            if (it != locals_.end()) return it->second.type;
        }
        return {TypeKind::I32};
    }

    std::pair<std::string, Type> emitExpr(const Expr& expression, std::ostringstream& out, std::optional<Type> expected = std::nullopt) {
        switch (expression.kind) {
            case Expr::Kind::Integer: {
                const auto& literal = static_cast<const IntegerExpr&>(expression);
                return {std::to_string(literal.value), expected.value_or(Type{TypeKind::I32})};
            }
            case Expr::Kind::Boolean: {
                const auto& literal = static_cast<const BooleanExpr&>(expression);
                return {literal.value ? "1" : "0", expected.value_or(Type{TypeKind::Bool})};
            }
            case Expr::Kind::Name: {
                const auto& name = static_cast<const NameExpr&>(expression).name;
                const Local& local = locals_.at(name);
                const std::string result = temp();
                out << "  " << result << " = load " << local.type.llvm() << ", ptr " << local.address << "\n";
                return {result, local.type};
            }
            case Expr::Kind::Unary: {
                const auto& unary = static_cast<const UnaryExpr&>(expression);
                const auto operand = emitExpr(*unary.operand, out);
                if (unary.op == "-") {
                    const std::string result = temp();
                    out << "  " << result << " = sub " << operand.second.llvm() << " 0, " << operand.first << "\n";
                    return {result, operand.second};
                }
                const std::string result = temp();
                out << "  " << result << " = xor i1 " << operand.first << ", 1\n";
                return {result, {TypeKind::Bool}};
            }
            case Expr::Kind::Binary: {
                const auto& binary = static_cast<const BinaryExpr&>(expression);
                const auto left = emitExpr(*binary.left, out);
                const auto right = emitExpr(*binary.right, out);
                const std::string result = temp();
                if (binary.op == "&&" || binary.op == "||") {
                    out << "  " << result << " = " << (binary.op == "&&" ? "and" : "or") << " i1 " << left.first << ", " << right.first << "\n";
                    return {result, {TypeKind::Bool}};
                }
                if (binary.op == "+" || binary.op == "-" || binary.op == "*" || binary.op == "/") {
                    const std::string opcode = binary.op == "+" ? "add" : binary.op == "-" ? "sub" : binary.op == "*" ? "mul" : "sdiv";
                    out << "  " << result << " = " << opcode << " " << left.second.llvm() << " " << left.first << ", " << right.first << "\n";
                    return {result, left.second};
                }
                const std::unordered_map<std::string, std::string> predicates{{"==", "eq"}, {"!=", "ne"}, {"<", "slt"}, {"<=", "sle"}, {">", "sgt"}, {">=", "sge"}};
                out << "  " << result << " = icmp " << predicates.at(binary.op) << " " << left.second.llvm() << " " << left.first << ", " << right.first << "\n";
                return {result, {TypeKind::Bool}};
            }
            case Expr::Kind::Call: {
                const auto& call = static_cast<const CallExpr&>(expression);
                const Function& function = *functions_.at(call.name);
                std::vector<std::pair<std::string, Type>> arguments;
                for (std::size_t i = 0; i < call.arguments.size(); ++i) arguments.push_back(emitExpr(*call.arguments[i], out, function.parameters[i].type));
                std::ostringstream rendered;
                for (std::size_t i = 0; i < arguments.size(); ++i) {
                    if (i) rendered << ", ";
                    rendered << function.parameters[i].type.llvm() << " " << arguments[i].first;
                }
                if (function.return_type.kind == TypeKind::Void) {
                    out << "  call void @" << function.name << "(" << rendered.str() << ")\n";
                    return {"", function.return_type};
                }
                const std::string result = temp();
                out << "  " << result << " = call " << function.return_type.llvm() << " @" << function.name << "(" << rendered.str() << ")\n";
                return {result, function.return_type};
            }
        }
        fail("unsupported expression in LLVM emitter", expression.line, expression.column);
    }

    bool emitBlock(const std::vector<StatementPtr>& statements, std::ostringstream& out, const Type& return_type) {
        bool terminated = false;
        for (const auto& statement : statements) {
            if (terminated) break;
            switch (statement->kind) {
                case Statement::Kind::Let: {
                    const auto& let = static_cast<const LetStatement&>(*statement);
                    const auto value = emitExpr(*let.value, out, let.declared);
                    out << "  store " << value.second.llvm() << " " << value.first << ", ptr " << locals_.at(let.name).address << "\n";
                    break;
                }
                case Statement::Kind::Return: {
                    const auto& ret = static_cast<const ReturnStatement&>(*statement);
                    if (!ret.value) out << "  ret void\n";
                    else {
                        const auto value = emitExpr(*ret.value, out, return_type);
                        out << "  ret " << value.second.llvm() << " " << value.first << "\n";
                    }
                    terminated = true;
                    break;
                }
                case Statement::Kind::Expression:
                    emitExpr(*static_cast<const ExpressionStatement&>(*statement).expression, out);
                    break;
                case Statement::Kind::If: {
                    const auto& conditional = static_cast<const IfStatement&>(*statement);
                    const auto condition = emitExpr(*conditional.condition, out);
                    const std::string then_label = label("if_then");
                    const std::string else_label = label("if_else");
                    const std::string merge_label = label("if_merge");
                    out << "  br i1 " << condition.first << ", label %" << then_label << ", label %" << else_label << "\n";
                    out << then_label << ":\n";
                    const bool then_terminated = emitBlock(conditional.then_body, out, return_type);
                    if (!then_terminated) out << "  br label %" << merge_label << "\n";
                    out << else_label << ":\n";
                    const bool else_terminated = conditional.else_body.empty() ? false : emitBlock(conditional.else_body, out, return_type);
                    if (!else_terminated) out << "  br label %" << merge_label << "\n";
                    out << merge_label << ":\n";
                    terminated = then_terminated && else_terminated;
                    if (terminated) out << "  unreachable\n";
                    break;
                }
                case Statement::Kind::While: {
                    const auto& loop = static_cast<const WhileStatement&>(*statement);
                    const std::string head = label("while_head");
                    const std::string body = label("while_body");
                    const std::string exit = label("while_exit");
                    out << "  br label %" << head << "\n";
                    out << head << ":\n";
                    const auto condition = emitExpr(*loop.condition, out);
                    out << "  br i1 " << condition.first << ", label %" << body << ", label %" << exit << "\n";
                    out << body << ":\n";
                    const bool body_terminated = emitBlock(loop.body, out, return_type);
                    if (!body_terminated) out << "  br label %" << head << "\n";
                    out << exit << ":\n";
                    break;
                }
            }
        }
        return terminated;
    }

    void emitFunction(const Function& function, std::ostringstream& out) {
        temp_counter_ = 0;
        label_counter_ = 0;
        locals_.clear();
        std::vector<std::pair<std::string, Type>> collected;
        for (const Parameter& parameter : function.parameters) collected.emplace_back(parameter.name, parameter.type);
        std::unordered_map<std::string, Type> known;
        for (const Parameter& parameter : function.parameters) known.emplace(parameter.name, parameter.type);
        collectLocals(function.body, collected, known);
        for (const auto& local : collected) {
            if (locals_.find(local.first) == locals_.end()) locals_.emplace(local.first, Local{local.second, "%" + escapeName(local.first) + ".addr"});
        }
        out << "; function: " << function.name << "\n";
        out << "define " << function.return_type.llvm() << " @" << function.name << "(";
        for (std::size_t i = 0; i < function.parameters.size(); ++i) {
            if (i) out << ", ";
            out << function.parameters[i].type.llvm() << " %" << escapeName(function.parameters[i].name);
        }
        out << ") {\nentry:\n";
        for (const auto& local : collected) {
            if (locals_.find(local.first) == locals_.end()) continue;
            if (local.first.empty()) continue;
            const Local& storage = locals_.at(local.first);
            out << "  " << storage.address << " = alloca " << storage.type.llvm() << "\n";
        }
        for (const Parameter& parameter : function.parameters) {
            const Local& storage = locals_.at(parameter.name);
            out << "  store " << parameter.type.llvm() << " %" << escapeName(parameter.name) << ", ptr " << storage.address << "\n";
        }
        const bool terminated = emitBlock(function.body, out, function.return_type);
        if (!terminated && function.return_type.kind == TypeKind::Void) out << "  ret void\n";
        else if (!terminated) fail("non-void function '" + function.name + "' has no terminating return", function.line, 1);

        out << "}\n";
    }

    const Program& program_;
    std::string target_;
    std::unordered_map<std::string, const Function*> functions_;
    std::unordered_map<std::string, Local> locals_;
    int temp_counter_ = 0;
    int label_counter_ = 0;
};

static std::string readFile(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) fail("cannot open input file '" + path + "'");
    std::ostringstream contents;
    contents << input.rdbuf();
    return contents.str();
}

static void writeFile(const std::string& path, const std::string& contents) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) fail("cannot open output file '" + path + "'");
    output << contents;
    if (!output) fail("failed writing output file '" + path + "'");
}

static void printUsage(const char* program) {
    std::cerr << "usage: " << program << " [--target=TRIPLE] INPUT.hf [-o OUTPUT.ll]\n"
              << "       " << program << " --help\n";
}

} // namespace hf0

int main(int argc, char** argv) {
    using namespace hf0;
    try {
        if (argc < 2) {
            printUsage(argv[0]);
            return 2;
        }
        std::string input_path;
        std::string output_path;
        std::string target = "x86_64-pc-linux-gnu";
        for (int index = 1; index < argc; ++index) {
            const std::string argument(argv[index]);
            if (argument == "--help" || argument == "-h") {
                printUsage(argv[0]);
                return 0;
            }
            if (argument.rfind("--target=", 0) == 0) {
                target = argument.substr(std::string("--target=").size());
                if (target.empty()) fail("--target cannot be empty");
                continue;
            }
            if (argument == "--target") {
                if (index + 1 >= argc) fail("--target requires a value");
                target = argv[++index];
                continue;
            }
            if (argument == "-o" || argument == "--output") {
                if (index + 1 >= argc) fail("-o/--output requires a path");
                output_path = argv[++index];
                continue;
            }
            if (!argument.empty() && argument[0] == '-') fail("unknown option '" + argument + "'");
            if (!input_path.empty()) fail("multiple input files are not supported by the seed compiler");
            input_path = argument;
        }
        if (input_path.empty()) {
            printUsage(argv[0]);
            return 2;
        }
        const std::string source = readFile(input_path);
        Lexer lexer(source);
        Parser parser(lexer.run());
        Program program = parser.parse();
        Validator validator;
        validator.run(program);
        const std::string llvm = LLVMEmitter(program, target).emit();
        if (output_path.empty()) {
            std::cout << llvm;
        } else {
            writeFile(output_path, llvm);
            std::cerr << "holyfitra-bootstrap: wrote " << output_path << "\n";
        }
        return 0;
    } catch (const Diagnostic& diagnostic) {
        std::cerr << "holyfitra-bootstrap: error" << location(diagnostic.line, diagnostic.column) << ": " << diagnostic.what() << "\n";
        return 1;
    } catch (const std::exception& error) {
        std::cerr << "holyfitra-bootstrap: internal error: " << error.what() << "\n";
        return 1;
    }
}
