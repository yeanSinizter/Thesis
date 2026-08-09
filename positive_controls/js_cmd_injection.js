// Positive control: command execution with string concatenation (command injection shape).
const { execSync } = require("child_process");

function unsafeList(userPath) {
  return execSync("ls " + userPath, { encoding: "utf8" });
}

module.exports = { unsafeList };
