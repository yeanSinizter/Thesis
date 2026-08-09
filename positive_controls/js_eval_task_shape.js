// Task-aligned probe: CWE-94-style dynamic execution (eval).
// Intentionally unsafe; used only to test whether p/security-audit fires on this shape.
function unsafeEval(expr) {
  return eval(expr);
}

module.exports = { unsafeEval };
