/**
 * readonly-guard desktop half — the three-way mode switch.
 *
 * Lives at <hermes home>/plugins/readonly-guard/desktop/plugin.js; the Electron
 * shell COPIES it into desktop-plugins/readonly-guard/ (app-level, opt-in via
 * Capabilities -> Plugins) and loads THAT copy — a source edit needs a Rescan.
 * It talks to the Python half over the plugin-scoped namespace
 * /api/plugins/readonly-guard/ (ctx.rest), which writes the same state file the
 * agent half reads on every tool call.
 *
 * UI: one segmented control in the status bar (read-only | plan | writable) plus
 * a palette command per mode. Plain ESM, loaded uncompiled: jsx() calls, not JSX.
 */

import { haptic, host, queryClient, SegmentedControl, Tip, usePluginI18n, useQuery } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

const ID = 'readonly-guard'
/** The three postures, painted left to right: most restrictive first. */
const MODES = ['readonly', 'plan', 'writable']
/** Notification severity: tightening the guard is good news, loosening it is not. */
const KINDS = { readonly: 'success', plan: 'info', writable: 'warning' }

// Bound in register(ctx): ctx.rest is the only door to our own backend.
let api = null

async function setMode(mode) {
  const next = await api('/state', { method: 'POST', body: { mode } })
  queryClient.invalidateQueries({ queryKey: [ID, 'state'] })
  haptic('tap')
  host.notify({ kind: KINDS[mode], message: `${ID}: ${mode}` })
  return next
}

function ModeControl() {
  const t = usePluginI18n(ID)
  const { data, isError } = useQuery({
    queryKey: [ID, 'state'],
    queryFn: () => api('/state'),
    refetchInterval: 5000 // picks up /readonly typed in chat
  })
  const mode = data && typeof data.mode === 'string' ? data.mode : null
  const unavailable = isError || mode === null

  return jsx(Tip, {
    label: unavailable ? t('unavailable') : t(`tip_${mode}`),
    children: jsx(SegmentedControl, {
      disabled: unavailable,
      onChange: next => {
        if (!unavailable && next !== mode) {
          setMode(next)
        }
      },
      options: MODES.map(id => ({ id, label: t(`mode_${id}`) })),
      value: mode || MODES[0]
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
        tip_readonly: 'Read-only: every non-inspection tool call is blocked — click "plan" to plan instead',
        tip_plan: 'Plan: inspection tools only, every turn goes to the plan skill — click "writable" to allow writes',
        tip_writable: 'Writable: nothing is blocked — click "read-only" to block writes',
        unavailable: 'Guard state unavailable — is the readonly-guard plugin enabled in config.yaml?'
      }
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 140,
      render: () => jsx(ModeControl, {})
    })

    MODES.forEach((mode, index) => {
      ctx.register({
        id: `cmd-${mode}`,
        area: 'PALETTE_AREA',
        order: 200 + index,
        data: { label: `${ID}: ${mode}`, run: () => setMode(mode) }
      })
    })
  }
}
