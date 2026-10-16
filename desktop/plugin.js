/**
 * readonly-guard desktop half — the clickable switch.
 *
 * Lives at <hermes home>/plugins/readonly-guard/desktop/plugin.js; the Electron
 * shell copies it into desktop-plugins/readonly-guard/ (app-level, opt-in via
 * Capabilities -> Plugins). It talks to the Python half over the plugin-scoped
 * namespace /api/plugins/readonly-guard/ (ctx.rest), which flips the same state
 * file the agent half reads on every tool call.
 *
 * UI: one statusbar chip (click = toggle) + two palette commands.
 * Plain ESM, loaded uncompiled: jsx() calls, not JSX syntax.
 */

import { cn, haptic, host, queryClient, Tip, usePluginI18n, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

const ID = 'readonly-guard'

// Bound in register(ctx): ctx.rest is the only door to our own backend.
let api = null

async function post(path, body) {
  const next = await api(path, { method: 'POST', body })
  queryClient.invalidateQueries({ queryKey: [ID, 'state'] })
  return next
}

export async function toggle() {
  const next = await post('/toggle')
  const on = next && next.enabled
  haptic('tap')
  host.notify({ kind: on ? 'info' : 'warning', message: on ? 'read-only: ON' : 'read-only: OFF — writes allowed' })
  return next
}

function Chip() {
  const t = usePluginI18n(ID)
  const { data, isError } = useQuery({
    queryKey: [ID, 'state'],
    queryFn: () => api('/state'),
    refetchInterval: 5000 // picks up /readonly typed in chat
  })
  const on = Boolean(data && data.enabled)
  const unavailable = isError || data === undefined

  return jsx(Tip, {
    label: unavailable ? t('unavailable') : on ? t('tipOn') : t('tipOff'),
    children: jsx('button', {
      type: 'button',
      disabled: unavailable,
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        unavailable
          ? 'text-(--ui-text-quaternary)'
          : on
            ? 'text-(--ui-text-secondary) hover:bg-(--chrome-action-hover) hover:text-foreground'
            : 'text-(--ui-accent) hover:bg-(--chrome-action-hover)'
      ),
      onClick: () => { if (!unavailable) toggle() },
      children: unavailable ? t('unknown') : on ? t('on') : t('off')
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
        on: 'read-only',
        off: 'writable',
        unknown: 'read-only ?',
        tipOn: 'Read-only guard is ON — click to allow writes',
        tipOff: 'Read-only guard is OFF — click to block writes',
        unavailable: 'Guard state unavailable — is the readonly-guard plugin enabled in config.yaml?',
        cmdOn: 'Read-only guard: turn ON',
        cmdOff: 'Read-only guard: turn OFF'
      }
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 140,
      render: () => jsx(Chip, {})
    })

    ctx.register({
      id: 'cmd-on',
      area: 'PALETTE_AREA',
      order: 200,
      data: {
        label: 'Read-only guard: turn ON',
        run: () => post('/state', { enabled: true })
      }
    })

    ctx.register({
      id: 'cmd-off',
      area: 'PALETTE_AREA',
      order: 201,
      data: {
        label: 'Read-only guard: turn OFF',
        run: () => post('/state', { enabled: false })
      }
    })
  }
}
