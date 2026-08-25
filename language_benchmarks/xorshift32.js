if (process.argv.length !== 4) process.exit(2);
const iterations = Number.parseInt(process.argv[2], 10);
let state = Number.parseInt(process.argv[3], 10) >>> 0;
const started = process.hrtime.bigint();
for (let index = 0; index < iterations; index += 1) {
  state = (state ^ (state << 13)) >>> 0;
  state = (state ^ (state >>> 17)) >>> 0;
  state = (state ^ (state << 5)) >>> 0;
}
const elapsed = process.hrtime.bigint() - started;
console.log(`result=${state} loop_ns=${elapsed}`);
