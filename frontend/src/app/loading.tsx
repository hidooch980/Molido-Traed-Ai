/**
 * What a page shows while the server is still building it.
 *
 * Every one of the thirty-eight pages here is `force-dynamic`, which is right:
 * a dashboard that caches an account balance is a dashboard that lies. But
 * without this file Next has nothing to render during that wait, so clicking a
 * menu item froze the page you were already on - for a second on the cheap
 * screens and four on the decision chain - and then replaced it all at once.
 * Nothing on screen acknowledged the click, so the honest reading was that the
 * click had not worked.
 *
 * This changes no data and no freshness. It is the difference between a page
 * that is loading and a page that appears to be broken.
 *
 * **It mirrors the real layout rather than spinning.** A spinner says
 * "something is happening"; a header block over a row of stat tiles over a
 * table says "the thing you asked for is arriving, and here is its shape" -
 * and because the skeleton occupies the same space the content will, nothing
 * jumps when it lands.
 */

function Bar({ w = "100%", h = "0.9rem" }: { w?: string; h?: string }) {
  return (
    <span
      className="skeleton-bar"
      style={{ width: w, height: h }}
      aria-hidden="true"
    />
  );
}

export default function Loading() {
  return (
    // Announced politely: a screen reader should hear that something is
    // loading, and should not have the whole skeleton read out to it.
    <div className="space-y-6" role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">در حال بارگذاری</span>

      <header className="page-header">
        <div className="min-w-0 space-y-2">
          <Bar w="min(22rem, 60%)" h="1.6rem" />
          <Bar w="min(34rem, 85%)" h="0.8rem" />
        </div>
      </header>

      {/* Four tiles, because that is what most pages open with. */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="panel p-4 space-y-3">
            <Bar w="55%" h="0.7rem" />
            <Bar w="40%" h="1.5rem" />
            <Bar w="70%" h="0.65rem" />
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="p-4 space-y-2">
          <Bar w="30%" h="0.9rem" />
          <Bar w="52%" h="0.7rem" />
        </div>
        <div className="p-4 space-y-3">
          {/* Six rows: enough to fill a first screen, few enough that a page
              with three real rows does not visibly shrink when it arrives. */}
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Bar key={i} h="1.1rem" />
          ))}
        </div>
      </div>
    </div>
  );
}
