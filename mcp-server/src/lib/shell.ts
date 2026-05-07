/** Quote a string for safe inclusion in a shell command (Bourne-compatible).
 *  Wraps in single quotes; escapes contained single quotes via `'\''`.
 *  Always prefer this over string interpolation when constructing shell commands —
 *  even for "trusted" values (RPC responses, system paths) — to keep audit clean. */
export function shellQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`
}
