/**
 * The decision chain, drawn from the gates that actually exist.
 *
 * The names below are the eight stages `app/pipeline/decide.py` records into
 * every trace - `cognition`, `levels`, `expected_value`, `portfolio`, `risk`,
 * `stress`, `challenge`, `intent`. That matters more than it sounds: a diagram
 * on a landing page is the easiest place in a product to draw a system nobody
 * built, and every competitor infographic in this category is a picture of an
 * architecture rather than of a program. This one can be checked against a
 * trace, because the trace uses these strings.
 *
 * It is a server component and reads nothing. The landing page is public, and
 * live figures on it would be published to anybody who loaded the URL.
 *
 * **The last row is the honest part.** Most evaluations stop before the end,
 * and a chain drawn as an unbroken pipeline from left to right tells the
 * opposite story - it implies that a decision usually arrives. Each gate is
 * drawn as something that can stop, and the note underneath says that stopping
 * is the ordinary outcome rather than the failure case.
 */

export interface ChainLabels {
  title: string;
  body: string;
  note: string;
  stops: string;
  gates: { key: string; name: string; asks: string }[];
}

export function ChainDiagram({ labels }: { labels: ChainLabels }) {
  return (
    <section className="landing-section">
      <h2 className="landing-h2">{labels.title}</h2>
      <p className="landing-section-lede">{labels.body}</p>

      <ol className="chain">
        {labels.gates.map((gate, index) => (
          <li key={gate.key} className="chain-gate">
            <div className="chain-rail" aria-hidden="true">
              <span className="chain-node" />
              {index < labels.gates.length - 1 && <span className="chain-line" />}
            </div>
            <div className="chain-body">
              <div className="chain-head">
                <span className="chain-n">{String(index + 1).padStart(2, "0")}</span>
                <h3 className="chain-name">{gate.name}</h3>
                {/* Every gate but the last is a veto. Saying so on each one is
                    the difference between a pipeline and a chain of refusals. */}
                {index < labels.gates.length - 1 && (
                  <span className="chain-veto">{labels.stops}</span>
                )}
              </div>
              <p className="chain-asks">{gate.asks}</p>
            </div>
          </li>
        ))}
      </ol>

      <p className="chain-note">{labels.note}</p>
    </section>
  );
}
