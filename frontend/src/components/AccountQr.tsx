import QRCode from "qrcode";

/**
 * The account number as a QR code, rendered on the server.
 *
 * The barcode beside it is for the eye: seven logins differing by one digit
 * in the middle are the same shape in a column, and a Code 39 pattern is a
 * different shape for each. This is for the phone. Reading a ten digit login
 * off a screen and typing it into a broker's app is where a transposed digit
 * becomes an order on the wrong account, and the whole reason to have a
 * machine-readable form on the page is that it removes the retyping.
 *
 * Rendered here rather than in the browser. The number is already on the
 * page, so there is nothing to hide, but generating it server-side means no
 * client bundle grows for a decoration and no viewer waits on JavaScript to
 * see it. `qrcode` returns an SVG string; the component is async, which Next
 * server components allow.
 *
 * Low error correction on purpose. The payload is ten digits at most, the
 * code is displayed rather than printed on a box that will be scuffed, and
 * higher correction only makes the modules smaller and the scan harder at
 * this size.
 */
export default async function AccountQr({
  value,
  size = 64,
  title,
}: {
  value: string;
  size?: number;
  title?: string;
}) {
  const payload = String(value ?? "").trim();
  if (!payload) return null;

  let svg: string;
  try {
    svg = await QRCode.toString(payload, {
      type: "svg",
      errorCorrectionLevel: "L",
      margin: 0,
      // The ink follows the surrounding text so the code reads in either
      // theme; a fixed black on a dark page is a code nobody can scan.
      color: { dark: "#000000", light: "#0000" },
      width: size,
    });
  } catch {
    // A code that cannot be generated is left out rather than replaced with
    // a broken one: a QR that scans to the wrong number is worse than none,
    // and the digits are printed beside it either way.
    return null;
  }

  // `qrcode` hard-codes its own fill; swapping it for currentColor is what
  // makes the theme follow. Done on the string because the library offers no
  // hook for it.
  const themed = svg
    .replace(/fill="#000000"/g, 'fill="currentColor"')
    .replace(/shape-rendering="[^"]*"/g, 'shape-rendering="crispEdges"');

  return (
    <span
      aria-label={title ?? payload}
      role="img"
      title={title ?? payload}
      style={{ display: "block", width: size, height: size, lineHeight: 0 }}
      dangerouslySetInnerHTML={{ __html: themed }}
    />
  );
}
