// Shows a tooltip when hovering or focusing an element with `data-qfc-datetime-tooltip`.
// The tooltip lists the same moment as relative time, in the user's timezone, the browser's timezone and UTC.
(() => {
  /** Matches the datetime elements marked by the server. */
  const SELECTOR = "[data-qfc-datetime-tooltip]";
  /** Id of the single tooltip element, referenced by `aria-describedby` on the shown datetime. */
  const TOOLTIP_ID = "qfc-datetime-tooltip";
  /** How long the pointer must rest on a datetime before the tooltip opens. */
  const OPEN_DELAY_MS = 300;
  /** How long the tooltip stays after the pointer leaves, so it can move onto the tooltip. */
  const CLOSE_DELAY_MS = 150;
  /** Minimum distance between the tooltip and the viewport edges. */
  const VIEWPORT_MARGIN_PX = 8;
  /** Distance between the datetime and the tooltip. */
  const ANCHOR_GAP_PX = 6;

  /** @type {HTMLElement} The single tooltip element, created by `init`. */
  let tooltip;
  /** @type {HTMLElement|null} The datetime element the tooltip is currently shown for. */
  let anchor = null;
  /** @type {number|undefined} The tooltip opens and closes after a short delay, this is the id of that waiting `setTimeout`. */
  let pendingTimeout;

  /**
   * Format a date with seconds, in the viewer's locale.
   *
   * @param {Date} date - The moment to format.
   * @param {string|undefined} timeZone - IANA time zone name, `undefined` for the browser's time zone.
   * @param {boolean} withTimeZoneName - Whether to append the short time zone name.
   * @returns {string|null} The formatted date, `null` when the browser does not know the time zone.
   */
  function formatDate(date, timeZone, withTimeZoneName) {
    // `dateStyle`/`timeStyle` cannot be combined with `timeZoneName`, so spell out the parts
    try {
      return new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone,
        timeZoneName: withTimeZoneName ? "short" : undefined,
      }).format(date);
    } catch (error) {
      console.warn(
        `datetime_tooltip: cannot format in time zone "${timeZone}"`,
        error,
      );
      return null;
    }
  }

  /**
   * Format a date relative to now, in the largest fitting unit.
   *
   * @param {Date} date - The moment to format.
   * @returns {string} The relative time.
   */
  function formatRelative(date) {
    const formatter = new Intl.RelativeTimeFormat(undefined, {
      numeric: "auto",
    });
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const units = [
      ["year", 60 * 60 * 24 * 365],
      ["month", 60 * 60 * 24 * 30],
      ["day", 60 * 60 * 24],
      ["hour", 60 * 60],
      ["minute", 60],
    ];

    for (const [unit, unitSeconds] of units) {
      if (Math.abs(seconds) >= unitSeconds) {
        return formatter.format(Math.round(seconds / unitSeconds), unit);
      }
    }

    return formatter.format(seconds, "second");
  }

  /**
   * Build the tooltip content for a datetime element.
   *
   * @param {HTMLElement} element - Element with `data-qfc-datetime-tooltip` and `data-tz`.
   * @returns {Array<[string, string]>} `[label, value]` pairs, the first one being the relative time with an empty label.
   */
  function getTooltipRows(element) {
    const date = new Date(element.dataset.qfcDatetimeTooltip);
    const userTimeZone = element.dataset.tz;
    const rows = [["", formatRelative(date)]];

    const userValue = formatDate(date, userTimeZone, true);

    if (userValue) {
      rows.push([userTimeZone, userValue]);
    }

    // Only show the browser's time zone when it would read differently from the user's time zone
    const browserValue = formatDate(date, undefined, true);

    if (browserValue !== userValue) {
      const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      rows.push([`${browserTimeZone} (browser)`, browserValue]);
    }

    rows.push(["UTC", formatDate(date, "UTC", false)]);

    return rows;
  }

  /**
   * Create an element with a class and optional text.
   *
   * @param {string} tagName - The element's tag.
   * @param {string} className - The element's class.
   * @param {string} [text] - The element's text.
   * @returns {HTMLElement} The new element.
   */
  function createElement(tagName, className, text = "") {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = text;

    return element;
  }

  /**
   * Create one tooltip row.
   *
   * @param {string} label - Row label, empty for the relative time row.
   * @param {string} value - Row value.
   * @returns {HTMLElement} The row element.
   */
  function buildRow(label, value) {
    const row = createElement("div", "qfc-datetime-tooltip-row");
    row.classList.toggle("qfc-datetime-tooltip-relative", !label);
    row.append(
      createElement("span", "qfc-datetime-tooltip-label", label),
      createElement("span", "qfc-datetime-tooltip-value", value),
    );

    return row;
  }

  /**
   * Place the tooltip below the element, or above it when there is no room.
   *
   * @param {HTMLElement} element - The datetime element the tooltip belongs to.
   */
  function position(element) {
    const anchorRect = element.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();

    let top = anchorRect.bottom + ANCHOR_GAP_PX;

    if (top + tipRect.height > window.innerHeight - VIEWPORT_MARGIN_PX) {
      top = anchorRect.top - tipRect.height - ANCHOR_GAP_PX;
    }

    const maxLeft = window.innerWidth - tipRect.width - VIEWPORT_MARGIN_PX;
    const left = Math.max(
      VIEWPORT_MARGIN_PX,
      Math.min(anchorRect.left, maxLeft),
    );

    tooltip.style.top = `${Math.max(VIEWPORT_MARGIN_PX, top)}px`;
    tooltip.style.left = `${left}px`;
  }

  /**
   * Move `aria-describedby` from the previous datetime to this one, so screen readers read the tooltip for it.
   *
   * @param {HTMLElement|null} element - The new anchor, `null` for none.
   */
  function setAnchor(element) {
    anchor?.removeAttribute("aria-describedby");
    anchor = element;
    anchor?.setAttribute("aria-describedby", TOOLTIP_ID);
  }

  /**
   * Show the tooltip for a datetime element, which becomes the anchor.
   * Rebuilds the rows from that element's datetime and places the tooltip next to it.
   *
   * @param {HTMLElement} element - The datetime element to show the tooltip for.
   */
  function open(element) {
    const rows = getTooltipRows(element);
    tooltip.replaceChildren(
      ...rows.map(([label, value]) => buildRow(label, value)),
    );
    tooltip.hidden = false;
    setAnchor(element);
    position(element);
  }

  /** Hide the tooltip right away, cancel the pending open or close, and clear the anchor. */
  function close() {
    clearTimeout(pendingTimeout);
    tooltip.hidden = true;
    setAnchor(null);
  }

  /**
   * Run an open or close after a delay, replacing the pending action.
   *
   * @param {Function} action - What to run.
   * @param {number} delay - Delay in milliseconds.
   */
  function schedule(action, delay) {
    clearTimeout(pendingTimeout);
    pendingTimeout = setTimeout(action, delay);
  }

  /**
   * Find the datetime element an event happened in.
   *
   * @param {EventTarget|null} node - The event target.
   * @returns {HTMLElement|null} The closest datetime element, or `null`.
   */
  function findTarget(node) {
    return node instanceof Element ? node.closest(SELECTOR) : null;
  }

  /**
   * Open the tooltip when a mouse or pen hovers over a datetime element.
   *
   * @param {PointerEvent} event
   */
  function onPointerOver(event) {
    // Ignore touch, otherwise it would open whenever a finger lands on a datetime element.
    // Only proceed if the pointer is not from a touch device, this means only mouse or pen.
    const element = event.pointerType !== "touch" && findTarget(event.target);

    if (!element) {
      return;
    }

    if (element === anchor && !tooltip.hidden) {
      // Back on the shown datetime, keep it open
      clearTimeout(pendingTimeout);
    } else {
      schedule(() => open(element), OPEN_DELAY_MS);
    }
  }

  /**
   * Close the tooltip when the pointer leaves a datetime element or the tooltip itself.
   *
   * @param {PointerEvent} event
   */
  function onPointerOut(event) {
    const element = findTarget(event.target);

    if (
      !element ||
      element.contains(event.relatedTarget) ||
      tooltip.contains(event.relatedTarget)
    ) {
      return;
    }

    schedule(close, CLOSE_DELAY_MS);
  }

  /**
   * Open the tooltip right away when a datetime element, or a link containing one, gets keyboard focus.
   *
   * @param {FocusEvent} event
   */
  function onFocusIn(event) {
    const element =
      findTarget(event.target) ?? event.target.querySelector?.(SELECTOR);

    if (element) {
      schedule(() => open(element), 0);
    }
  }

  /**
   * Close the tooltip when focus leaves its datetime element.
   *
   * @param {FocusEvent} event
   */
  function onFocusOut(event) {
    if (anchor && event.target.contains(anchor)) {
      close();
    }
  }

  /**
   * Close the tooltip on Escape.
   *
   * @param {KeyboardEvent} event
   */
  function onKeyDown(event) {
    if (event.key === "Escape" && anchor) {
      close();
    }
  }

  /**
   * Make datetime elements reachable by keyboard, unless they already sit inside a focusable link or button.
   *
   * @param {Element} root - The element to search, itself included.
   */
  function makeFocusableWithin(root) {
    const elements = [...root.querySelectorAll(SELECTOR)];

    if (root.matches(SELECTOR)) {
      elements.push(root);
    }

    for (const element of elements) {
      if (!element.closest("a, button")) {
        element.tabIndex = 0;
      }
    }
  }

  /** Create the tooltip element and attach the listeners. */
  function init() {
    tooltip = createElement("div", "qfc-datetime-tooltip");
    tooltip.id = TOOLTIP_ID;
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    tooltip.addEventListener("pointerenter", () =>
      clearTimeout(pendingTimeout),
    );
    tooltip.addEventListener("pointerleave", () =>
      schedule(close, CLOSE_DELAY_MS),
    );
    document.body.appendChild(tooltip);

    makeFocusableWithin(document.documentElement);

    // Datetimes added after page load, such as admin inline rows, also need to be keyboard focusable.
    new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            makeFocusableWithin(node);
          }
        }
      }
    }).observe(document.body, { childList: true, subtree: true });

    document.addEventListener("pointerover", onPointerOver);
    document.addEventListener("pointerout", onPointerOut);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("keydown", onKeyDown);

    // The tooltip is positioned once, relative to the window.
    // Scrolling or resizing moves the datetime, but not the tooltip, so close it instead.
    window.addEventListener("scroll", close, { capture: true, passive: true });
    window.addEventListener("resize", close, { passive: true });
  }

  // Wait for the page to load, then initialize the tooltip.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
