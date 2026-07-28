import type { Status } from "../lib/types";

interface Props {
  status: Status | null;
  error: string | null;
  onDismissError: () => void;
}

/**
 * The instrument readout.
 *
 * Entry count, provider, and spend live here permanently and quietly — spend in
 * particular should never be something you have to go looking for. Errors take
 * the bar over when they occur rather than opening a dialog, because a modal
 * over your journal to report a failed background call is disproportionate.
 */
export function StatusBar({ status, error, onDismissError }: Props) {
  if (error) {
    return (
      <footer className="statusbar statusbar--error" role="alert">
        <span className="micro statusbar__error">{error}</span>
        <button className="micro statusbar__dismiss" onClick={onDismissError}>
          dismiss
        </button>
      </footer>
    );
  }

  if (!status) {
    return <footer className="statusbar" />;
  }

  const spend = status.spend_this_month_usd;
  const nearCeiling =
    status.cost_ceiling_usd > 0 && spend >= status.cost_ceiling_usd * 0.8;

  return (
    <footer className="statusbar">
      <span className="micro tnum statusbar__item">
        {status.entries} {status.entries === 1 ? "entry" : "entries"}
      </span>

      <span className="statusbar__spacer" />

      {status.offline ? (
        <span className="micro statusbar__item statusbar__item--muted" title="No model configured">
          offline
        </span>
      ) : (
        <>
          <span className="micro statusbar__item">{status.model}</span>
          <span
            className={`micro tnum statusbar__item${nearCeiling ? " statusbar__item--warn" : ""}`}
            title={`This month, against a $${status.cost_ceiling_usd.toFixed(2)} ceiling`}
          >
            ${spend.toFixed(3)}
          </span>
        </>
      )}
    </footer>
  );
}
