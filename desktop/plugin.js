/**
 * readonly-guard desktop half — the three-way mode switch, PER SESSION.
 *
 * Lives at <hermes home>/plugins/readonly-guard/desktop/plugin.js; the Electron
 * shell COPIES it into desktop-plugins/readonly-guard/ (app-level, opt-in via
 * Capabilities -> Plugins) and loads THAT copy — a source edit needs a Rescan.
 * It talks to the Python half over the plugin-scoped namespace
 * /api/plugins/readonly-guard/ (ctx.rest), which writes the same per-session table
 * the agent half reads on every tool call.
 *
 * Scope: the STORED (durable) id of the focused chat — the same string the agent
 * reports as its session_id, so the chip and the guard agree on which session they
 * mean. A fresh draft has no such id yet, so the chip then edits the DEFAULT that new
 * sessions start with (POST with no `session`), and says so in its tooltip.
 *
 * Contributions MUST name their area with the SDK's constants. A literal — even one
 * spelled exactly like the constant, e.g. 'PALETTE_AREA' rather than PALETTE_AREA
 * (whose value is 'palette') — registers fine and never renders, which is how 1.1
 * shipped three dead palette rows.
 */

import { haptic, host, PALETTE_AREA, queryClient, SegmentedControl, STATUSBAR_AREAS, Tip, usePluginI18n, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

const ID = 'readonly-guard'
/** The label set, and the fallback when the payload does not carry `modes`. */
const MODES = ['readonly', 'plan', 'writable']
/** Notification severity: tightening the guard is good news, loosening it is not. */
const KINDS = { readonly: 'success', plan: 'info', writable: 'warning' }

// Bound in register(ctx): ctx.rest is the only door to our own backend.
let api = null

/** The focused chat's stored (durable) session id; '' when the chat is a fresh draft. */
function scopeNow() {
  return (host.state.focusedStoredSessionId && host.state.focusedStoredSessionId.get()) || ''
}

/** The same id, reactively, for a component. */
function useScope() {
  return useValue(host.state.focusedStoredSessionId) || ''
}

async function setMode(mode, session = scopeNow()) {
  // No session: the body carries no `session`, which the backend reads as "the default
  // for new sessions" — never as "the machine".
  const body = session ? { mode, session } : { mode }
  const next = await api('/state', { method: 'POST', body })
  queryClient.invalidateQueries({ queryKey: [ID, 'state'] })
  haptic('tap')
  host.notify({
    kind: KINDS[mode],
    message: session ? `${ID}: ${mode}` : `${ID}: new sessions start ${mode}`
  })
  return next
}

function ModeControl() {
  const t = usePluginI18n(ID)
  const session = useScope()
  const { data, isError } = useQuery({
    queryKey: [ID, 'state', session],
    queryFn: () => api(session ? `/state?session=${encodeURIComponent(session)}` : '/state'),
    refetchInterval: 5000 // picks up /readonly typed in chat
  })
  const mode = data && typeof data.mode === 'string' ? data.mode : null
  // The payload publishes the mode list, so a mode added server-side still appears.
  const modes = data && Array.isArray(data.modes) && data.modes.length > 0 ? data.modes : MODES
  // No response yet is a loading tick; only a failed request is a broken backend.
  const loading = !isError && mode === null
  const disabled = isError || loading
  const tip = isError ? t('unavailable') : loading ? t('loading') : session ? t(`tip_${mode}`) : t('tip_draft')

  return jsx(Tip, {
    label: tip,
    // The wrapper is load-bearing: Tip arms its tooltip with `asChild`, which clones
    // the child to hand it the trigger's props and ref — SegmentedControl spreads
    // neither, so wrapping it directly would leave the tooltip unable to open.
    children: jsx('span', {
      className: 'inline-flex h-full items-center',
      children: jsx(SegmentedControl, {
        disabled,
        onChange: next => {
          if (!disabled && next !== mode) {
            setMode(next, session)
          }
        },
        options: modes.map(id => ({ id, label: t(`mode_${id}`) })),
        value: mode || MODES[0]
      })
    })
  })
}

export default {
  id: ID,
  name: 'Read-only guard',
  // Opt-in: shows in Capabilities -> Plugins, dark until the user enables it.
  defaultEnabled: false,
  register(ctx) {
    api = ctx.rest

    ctx.i18n.register({
      en: {
        mode_readonly: 'read-only',
        mode_plan: 'plan',
        mode_writable: 'writable',
        tip_readonly: 'Read-only for this session: every non-inspection tool call is blocked — click "plan" to plan instead',
        tip_plan: 'Plan for this session: inspection tools only, every turn goes to the plan skill — click "writable" to allow writes',
        tip_writable: 'Writable for this session: nothing is blocked — click "read-only" to block writes',
        tip_draft: 'No session yet — this sets the mode NEW sessions start in',
        loading: 'Checking the readonly-guard mode…',
        unavailable: 'Guard state unavailable — is the readonly-guard plugin enabled in config.yaml?'
      }
    })

    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 140,
      render: () => jsx(ModeControl, {})
    })

    MODES.forEach((mode, index) => {
      ctx.register({
        id: `cmd-${mode}`,
        area: PALETTE_AREA,
        order: 200 + index,
        // `id` is part of PaletteContribution; the row itself is keyed off the registration.
        data: {
          id: `cmd-${mode}`,
          label: `${ID}: ${mode} (this chat, or new sessions)`,
          run: () => setMode(mode)
        }
      })
    })
  }
}
