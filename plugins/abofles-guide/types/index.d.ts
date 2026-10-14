export type Guide = { line: string; ts: number }

declare module 'claude-code' {
  interface PluginState {
    // `hiddenKey`: the priorities (🔴🟡…) of the line the person hid (Hide or Use); the band stays down while the
    // ladder keeps those priorities, and comes back when one appears or goes.
    'abofles-guide': { guide: Guide | null; hiddenKey: string | null }
  }
}
