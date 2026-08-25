if (process.argv.length !== 4) process.exit(2);
const iterations = Number.parseInt(process.argv[2], 10) >>> 0;
let state = Number.parseInt(process.argv[3], 10) >>> 0;
for (let index = 0; index < iterations; index += 1) {
  state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
}
console.log(`result=${state}`);
