import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const source = readFileSync(join(import.meta.dirname, '..', 'src', 'client-sidebar.js'), 'utf8')

function loadPluginExports(desktopPicker) {
  let definition
  runInNewContext(source, {
    __DSH_DIRECTORY_PICKER__: desktopPicker,
    window: {
      __ModuleLoader__: {
        load(value) { definition = value },
      },
    },
  })
  assert.ok(definition)
  return definition.factory(name => {
    if (name === 'react') return { createElement: (type, props) => ({ type, props }) }
    throw new Error(`unexpected client dependency: ${name}`)
  })
}

test('sidebar is explicitly anchored on the right', () => {
  assert.match(source, /right: '16px'/)
  assert.match(source, /left: 'auto'/)
  assert.match(source, /width: 'min\(440px, calc\(100vw - 32px\)\)'/)
  assert.match(source, /'选择保存位置'/)
})

test('sidebar presents local recognition and never asks for a model key', () => {
  assert.doesNotMatch(source, /glmApiKey|GLM API Key|hasGlmApiKey|ocrProvider/)
  assert.doesNotMatch(source, /DeepSeek 模型|当前模型|模型识别/)
  assert.match(source, /'本地解析 \+ OCR 识别，无需模型或 API Key。'/)
  const settingsState = source.match(/const \[settings, setSettings\] = React\.useState\(\{[\s\S]*?\n      \}\)/)
  assert.ok(settingsState)
  assert.doesNotMatch(settingsState[0], /authCode: ''[\s\S]*apiKey/)
  assert.match(source, /privacyResult\.value\.recognition/)
})

test('the registered panel selects directories through the browser workspace or Desktop bridge', async () => {
  for (const desktop of [undefined, { pick: async () => 'desktop-directory' }]) {
    const plugin = loadPluginExports(desktop)
    const registered = new Map()
    const calls = []
    const services = {
      slots: {
        inject(_name, register) { register() },
        register(options, render) { registered.set(options.name, render) },
      },
      connection: { rpc: { call: (...args) => calls.push(args) } },
      uiWorkspace: { pickDirectory: async () => 'browser-directory' },
    }
    const context = Object.fromEntries(plugin.inject.map(name => [name, services[name]]))
    plugin.apply({ ...context, get: name => context[name] })

    const { call, pickDirectory } = registered.get('shell.overlay')().props
    call('getRuntimeStatus', { fixture: true })
    assert.deepEqual(calls.map(([channel, method, body]) => [channel, method, { ...body }]), [
      ['/api', 'invoice/rpc', { endpoint: 'getRuntimeStatus', payload: { fixture: true } }],
    ])
    assert.equal(await pickDirectory(), desktop ? 'desktop-directory' : 'browser-directory')
  }
})

test('sidebar preserves every pending field update during one render batch', () => {
  assert.match(source, /setSettings\(previous => \(\{ \.\.\.previous, \[key\]: value \}\)\)/)
})

test('sidebar handles text and date input events from the DSH web host', () => {
  assert.match(source, /type: 'date', disabled, value: settings\.dateFrom, onInput: event => update\('dateFrom', event\.target\.value\)/)
  assert.match(source, /type: 'date', disabled, value: settings\.dateTo, onInput: event => update\('dateTo', event\.target\.value\)/)
})

test('sidebar replaces the last progress event with the terminal scan status', () => {
  assert.match(source, /progress: next\.running \? \(next\.progress \|\| previous\.progress\) : \(next\.status \|\| next\.progress \|\| previous\.progress\)/)
})

test('directory picker applies a selected DSH path and reports success', async () => {
  const { chooseOutputDirectory } = loadPluginExports()
  const updates = []
  const statuses = []
  await chooseOutputDirectory(
    async () => 'C:\\invoice-output',
    (...args) => updates.push(args),
    value => statuses.push([value.kind, value.message]),
  )
  assert.deepEqual(updates, [['savePath', 'C:\\invoice-output']])
  assert.deepEqual(statuses, [
    ['idle', ''],
    ['success', '已选择保存位置；保存设置后会重新校验。'],
  ])
})

test('directory picker leaves settings unchanged when the native chooser is cancelled', async () => {
  const { chooseOutputDirectory } = loadPluginExports()
  const updates = []
  const statuses = []
  await chooseOutputDirectory(
    async () => null,
    (...args) => updates.push(args),
    value => statuses.push([value.kind, value.message]),
  )
  assert.deepEqual(updates, [])
  assert.deepEqual(statuses, [['idle', '']])
})

test('directory picker reports a Host error without changing settings', async () => {
  const { chooseOutputDirectory } = loadPluginExports()
  const updates = []
  const statuses = []
  await chooseOutputDirectory(
    async () => { throw new Error('native dialog unavailable') },
    (...args) => updates.push(args),
    value => statuses.push([value.kind, value.message]),
  )
  assert.deepEqual(updates, [])
  assert.deepEqual(statuses, [
    ['idle', ''],
    ['error', '无法打开目录选择器。'],
  ])
})
