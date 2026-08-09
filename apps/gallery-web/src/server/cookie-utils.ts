/** Parses only a cookie name, never its signed value. Safe for shared tests. */
export function hasNamedCookie(cookieHeader: string, name: string): boolean {
  if (!name || /[=;\s]/.test(name)) return false;
  return cookieHeader.split(";").some((item) => item.trim().startsWith(`${name}=`));
}
