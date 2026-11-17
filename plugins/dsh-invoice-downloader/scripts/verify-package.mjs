import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const required = [
  'lib/index.js',
  'lib/activate.js',
  'src/client-sidebar.js',
  'cordis.patch.yml',
  'icon.svg',
  'locale/en.json',
  'locale/zh.json',
  'runtime/install.py',
  'runtime/health_check.py',
  'runtime/requirements-headless.txt',
  'runtime/engine/MANIFEST.json',
  'runtime/engine/src/invoice_engine/app_api.py',
  'runtime/engine/src/invoice_engine/local_recognition.py',
  'engine-adapter/dsh_runner.py',
  'engine-adapter/dsh_scan.py',
  'engine-adapter/ipc/protocol.py',
  'runtime/engine/src/invoice_engine/ipc/protocol.py',
  'LICENSE',
  'NOTICE',
]

for (const file of required) {
  assert.ok(existsSync(join(packageRoot, file)), `missing package file: ${file}`)
}

const manifest = JSON.parse(readFileSync(join(packageRoot, 'runtime/engine/MANIFEST.json'), 'utf8'))
assert.equal(typeof manifest.sourceSha, 'string')
assert.match(manifest.sourceSha, /^[0-9a-f]{40}$/)
assert.equal(manifest.sourceRepository, 'https://github.com/EthanYoQ/Invoice-Downloader')
assert.ok(Array.isArray(manifest.sourceFiles))

function collectPythonFiles(root, prefix = '') {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = join(root, entry.name)
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.isDirectory()) return collectPythonFiles(path, relativePath)
    return entry.isFile() && entry.name.endsWith('.py') ? [relativePath] : []
  })
}

function collectJavaScriptFiles(root, prefix = '') {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = join(root, entry.name)
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.isDirectory()) return collectJavaScriptFiles(path, relativePath)
    return entry.isFile() && entry.name.endsWith('.js') ? [relativePath] : []
  })
}

const bundledPythonFiles = collectPythonFiles(join(packageRoot, 'runtime', 'engine', 'src', 'invoice_engine'))
  .filter(file => file !== '__init__.py')
  .sort()
assert.deepEqual(bundledPythonFiles, manifest.sourceFiles)

assert.ok(
  bundledPythonFiles.includes('local_recognition.py'),
  'the bundled engine must ship the local recognition module',
)
for (const legacyModelSource of [
  'deepseek_extractor.py',
  'glm_fallback.py',
  'local_ocr.py',
  'recognition_chain.py',
]) {
  assert.ok(
    !bundledPythonFiles.includes(legacyModelSource),
    `legacy model recognition source must not be published: ${legacyModelSource}`,
  )
}

const legacyRecognitionSymbols = /recognition_chain|RecognitionChain|deepseek_extractor|DeepSeekExtractor|glm_fallback|create_glm_fallback|local_ocr_module/i
const scanAdapter = readFileSync(join(packageRoot, 'engine-adapter', 'dsh_scan.py'), 'utf8')
const runnerAdapter = readFileSync(join(packageRoot, 'engine-adapter', 'dsh_runner.py'), 'utf8')
assert.doesNotMatch(scanAdapter, legacyRecognitionSymbols)
assert.doesNotMatch(runnerAdapter, legacyRecognitionSymbols)
assert.match(scanAdapter, /LocalRecognitionWorker/)
assert.match(runnerAdapter, /run_scan\(config=config\)/)

const privateVerificationFiles = [
  'artifact_verifier.py',
  'audit_email_truth.py',
  'batch_validation.py',
  'build_truth_dataset.py',
  'model_calibration.py',
  'strict_truth_audit.py',
  'truth_contracts.py',
]
for (const file of privateVerificationFiles) {
  assert.ok(!bundledPythonFiles.includes(file), `private verification file must not be published: ${file}`)
}

const packageManifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'))
assert.ok(packageManifest.files.includes('lib/**/*.js'))
assert.ok(packageManifest.files.includes('lib/**/*.d.ts'))
assert.ok(!packageManifest.files.includes('lib/**'), 'publish only runtime JavaScript and declarations')
assert.equal(packageManifest.os, undefined)
assert.equal(packageManifest.cpu, undefined)

const directDshImports = collectJavaScriptFiles(join(packageRoot, 'lib'))
  .flatMap(file => Array.from(
    readFileSync(join(packageRoot, 'lib', file), 'utf8')
      .matchAll(/(?:from|import\s*\(?)\s*['"](@deepseek-ai\/[^'"]+)['"]/g),
    match => match[1],
  ))
assert.deepEqual(directDshImports.sort(), [
  '@deepseek-ai/dsh-client-connection',
  '@deepseek-ai/dsh-host-webserver',
])

const stagedPaths = [
  'runtime/.venv',
  'runtime/engine/.venv',
  '.runtime',
]
for (const path of stagedPaths) {
  assert.ok(!existsSync(join(packageRoot, path)), `runtime residue must not be packaged: ${path}`)
}

console.log('package layout and privacy exclusions: ok')
