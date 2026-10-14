import {configure} from '@testing-library/react';
configure({asyncUtilTimeout:15000});
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

/**
 * jsdom has no matchMedia. antd's responsiveObserver subscribes to it and then invokes the
 * listener with the MediaQueryList, destructuring `{ matches }` from that argument. A stub
 * whose addEventListener is a no-op passes silently, but a stub that calls listeners with
 * NO argument throws inside a React commit ("Cannot destructure property 'matches'"), which
 * makes a component fail to mount for reasons unrelated to the test. So the stub below
 * delivers a real MQL-like event.
 */
class MediaQueryListStub {
    matches = false;
    media: string;
    onchange: null = null;
    private listeners = new Set<(e: MediaQueryListEvent) => void>();
    constructor(query: string) {
        this.media = query;
    }
    addEventListener(_type: string, listener: (e: MediaQueryListEvent) => void) {
        this.listeners.add(listener);
    }
    removeEventListener(_type: string, listener: (e: MediaQueryListEvent) => void) {
        this.listeners.delete(listener);
    }
    addListener(listener: (e: MediaQueryListEvent) => void) {
        this.listeners.add(listener);
    }
    removeListener(listener: (e: MediaQueryListEvent) => void) {
        this.listeners.delete(listener);
    }
    dispatchEvent() {
        return true;
    }
    emit(matches: boolean) {
        this.matches = matches;
        const event = { matches, media: this.media } as MediaQueryListEvent;
        this.listeners.forEach((listener) => listener(event));
        return true;
    }
}

Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => new MediaQueryListStub(query)),
});

class ResizeObserver {
    observe() { }
    unobserve() { }
    disconnect() { }
}
globalThis.ResizeObserver = ResizeObserver;

/**
 * jsdom does not expose MutationObserver on the global. Testing Library's waitFor() and
 * findAllBy*() reach for it unconditionally, so without this they throw
 * "TypeError: MutationObserver is not a constructor" inside the query and the await never
 * settles — the test dies on its timeout with no useful message.
 *
 * This went unnoticed until a CSS change made antd's table mount rc-resize-observer for column
 * measurement, which imports the observer at module scope; before that nothing in the tree
 * touched it.
 *
 * The stub only needs the shape: waitFor uses the observer as an early exit and falls back to
 * polling, so a no-op implementation is correct and cannot make an assertion pass that would
 * otherwise fail.
 */
class MutationObserverStub {
    observe() { }
    unobserve() { }
    disconnect() { }
    takeRecords() {
        return [];
    }
}
if (typeof globalThis.MutationObserver === "undefined") {
    globalThis.MutationObserver =
        MutationObserverStub as unknown as typeof MutationObserver;
}

HTMLElement.prototype.scrollTo = vi.fn();
window.scrollTo = vi.fn();
