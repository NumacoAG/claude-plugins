/* Repeating table headers for Paged.js.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The vendored paged.polyfill.js has no thead-cloning logic at all. When a table
 * crosses a page boundary the continuation fragment is built by rebuildAncestors()
 * (vendor/paged.polyfill.js ~line 769), which walks the source ancestor chain and
 * clones every ancestor SHALLOW:
 *
 *     parent = ancestor.cloneNode(false);
 *     parent.setAttribute("data-split-from", parent.getAttribute("data-ref"));
 *
 * so page N+1 receives <table data-split-from="REF"><tbody data-split-from="REF">
 * <tr>... and the <thead> is simply never recreated. `display:table-header-group`
 * is inert here: Paged.js never asks Chrome to fragment the table, it hand-builds
 * every fragment itself. This handler recreates the header group.
 *
 * WHICH HOOK, AND WHY IT MATTERS
 * ------------------------------
 * The insertion runs in the `layout` hook, NOT in `afterPageLayout`.
 *
 * `layout` is triggered inside Layout.renderTo() immediately before every
 * findBreakToken() call (vendor lines 1463, 1488, 1547, 1566), and Hook.trigger()
 * applies its tasks synchronously (vendor line 423). So a synchronous handler has
 * already mutated the DOM by the time findBreakToken() measures the page, and the
 * repeated header's height is accounted for in the SAME layout pass: the row that
 * no longer fits is carried into the next break token naturally.
 *
 * Inserting in `afterPageLayout` would also "work", but only by way of the
 * ResizeObserver -> onOverflow -> stop() -> removePages() -> re-render cascade
 * (vendor line ~3167). That costs one extra pass per headered page and, when a
 * single tall row plus the header cannot fit one page, trips the "Layout repeated"
 * guard at vendor line 3096, which ABORTS pagination and silently truncates the
 * document. The `layout` hook removes that entire failure class.
 *
 * SCOPE
 * -----
 * Two branded table families are touched. `table.data` covers effort_table()
 * ("data effort") and line_items_table() ("data"), so numaco-report,
 * numaco-sow and numaco-timesheet. `table.trade-table` covers
 * build_trading_document.py, which emits its own "trade-table quotation-table |
 * delivery-table | priced-table" markup and never goes through effort_table(),
 * so numaco-trading-documents needs its own selector rather than riding along on
 * table.data. Any non-branded or layout table is left alone. numaco-slide-deck
 * does not use this pipeline at all (its own assemble() renders through
 * render_fixed(), no polyfill).
 */
(function () {
  "use strict";

  if (!window.Paged || !window.Paged.Handler || !window.Paged.registerHandlers) {
    return;
  }

  /* Every identity-bearing attribute must go, or the clone becomes a false match
   * for the built-in Splits handler, which looks up
   * prevPage.querySelector("[data-ref='REF']:not([data-split-to])") and then
   * stamps split/alignment bookkeeping on whatever it finds (vendor line 30198).
   * Duplicate ids would equally break the running-header and counter handlers. */
  var STRIP = [
    "data-ref",
    "data-split-from",
    "data-split-to",
    "data-split-original",
    "data-id",
    "id",
    "data-break-before",
    "data-previous-break-after",
    "data-lastsplitelement",
    "data-alignlastsplitelement"
  ];

  function sanitise(el) {
    var nodes = [el].concat(Array.prototype.slice.call(el.querySelectorAll("*")));
    for (var i = 0; i < nodes.length; i++) {
      for (var j = 0; j < STRIP.length; j++) {
        nodes[i].removeAttribute(STRIP[j]);
      }
    }
  }

  var RepeatTableHeader = class extends window.Paged.Handler {
    constructor(chunker, polisher, caller) {
      super(chunker, polisher, caller);
    }

    /* Fires immediately before each findBreakToken(). Synchronous on purpose. */
    layout(wrapper) {
      var chunker = this.chunker;
      var source = chunker && chunker.source;
      if (!source || typeof source.querySelector !== "function" || !wrapper) {
        return;
      }

      var fragments = wrapper.querySelectorAll(
        "table.data[data-split-from], table.trade-table[data-split-from]"
      );
      for (var i = 0; i < fragments.length; i++) {
        var table = fragments[i];

        /* Idempotency AND the no-double-header guarantee in one test. A genuine
         * continuation fragment never owns a thead; the first fragment is the
         * original table and always does, so it is skipped here as well as by
         * the [data-split-from] selector. The guard lives on the DOM rather than
         * in handler state because removePages() can re-run layout over freshly
         * rebuilt fragments. */
        if (table.querySelector(":scope > thead")) {
          continue;
        }

        /* Do not head a fragment that has not rendered a row yet: that is what
         * produces an orphan header page. A later `layout` trigger on the same
         * page picks it up once rows exist. */
        if (!table.querySelector("tbody > tr")) {
          continue;
        }

        /* Take the header from the authoritative parsed source (chunker.source,
         * set in Chunker.flow at vendor line 2904), never from the previous
         * page: on a three-page table the previous page's header is itself a
         * sanitised clone, and copying it forward would also re-copy stale
         * split bookkeeping. */
        var ref = table.getAttribute("data-split-from");
        if (!ref) {
          continue;
        }
        var sourceTable = source.querySelector('[data-ref="' + ref + '"]');
        if (!sourceTable || sourceTable.nodeName !== "TABLE") {
          continue;
        }
        var sourceHead = sourceTable.querySelector(":scope > thead");
        if (!sourceHead) {
          continue;
        }

        var clone = sourceHead.cloneNode(true);
        sanitise(clone);
        clone.setAttribute("data-repeated-header", "true");
        table.insertBefore(clone, table.firstChild);
      }
    }

    /* Safety net. If a page ends up holding a repeated header with no rows under
     * it (the break landed such that findBreakToken carried every row forward),
     * take the header back off. Removing content only shrinks the page, so this
     * can never trigger an overflow of its own. */
    afterPageLayout(pageElement) {
      if (!pageElement) {
        return;
      }
      var heads = pageElement.querySelectorAll("thead[data-repeated-header]");
      for (var i = 0; i < heads.length; i++) {
        var table = heads[i].closest("table");
        if (table && !table.querySelector("tbody > tr")) {
          heads[i].remove();
        }
      }
    }
  };

  window.Paged.registerHandlers(RepeatTableHeader);
})();
