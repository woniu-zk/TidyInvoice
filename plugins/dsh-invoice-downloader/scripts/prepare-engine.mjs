import { cpSync, existsSync, lstatSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(packageRoot, '..', '..')
const runtimeRoot = resolve(packageRoot, 'runtime')
const engineRoot = resolve(runtimeRoot, 'engine')
const sourceRoot = projectRoot
const engineSourceFiles = [
  'app_api.py',
  'app_services/__init__.py',
  'app_services/exports.py',
  'app_archive_adapter.py',
  'archive_pairing_service.py',
  'archive_pairing.py',
  'archive_service.py',
  'bounded_url_recovery.py',
  'brand_generated.py',
  'build_identity.py',
  'candidate_pipeline.py',
  'company_rules.py',
  'deferred_url_recovery.py',
  'document_acceptance.py',
  'document_types.py',
  'email_body_receipts.py',
  'email_channel.py',
  'email_fetcher.py',
  'expense_rules/__init__.py',
  'expense_rules/model.py',
  'expense_rules/loader.py',
  'expense_rules/engine.py',
  'expense_rules/store.py',
  'expense_rules/cli.py',
  'expense_rules/types.py',
  'extraction_pipeline.py',
  'frontend_run_context.py',
  'glm_runtime.py',
  'invoice_domain.py',
  'invoice_extractor.py',
  'local_recognition.py',
  'mailbox_scanner.py',
  'main.py',
  'pairing_engine.py',
  'pdf_converter.py',
  'pinned_http.py',
  'provider_baiwang.py',
  'provider_direct_invoice.py',
  'report_service.py',
  'run_coordinator.py',
  'run_evidence.py',
  'run_lifecycle.py',
  'run_state_store.py',
  'url_recovery_worker.py',
  'url_security.py',
  'url_trace_sanitizer.py',
  'user_settings.py',
]
// The plugin has no adapter-owned Python sources any more: local recognition is
// vendored from the product engine (`local_recognition.py`), so the bundled
// engine is exactly the product source list plus the IPC protocol module.

function requireInside(parent, child) {
  const rel = relative(parent, child)
  if (rel === '' || rel === '..' || rel.startsWith(`..${sep}`) || rel.includes(`${sep}..${sep}`)) {
    throw new Error(`path must be inside ${parent}: ${child}`)
  }
}

function copyFile(source, destination) {
  const stat = lstatSync(source)
  if (!stat.isFile()) throw new Error(`expected file: ${source}`)
  mkdirSync(dirname(destination), { recursive: true })
  cpSync(source, destination, { force: true })
}

requireInside(packageRoot, runtimeRoot)
requireInside(runtimeRoot, engineRoot)
if (!existsSync(join(sourceRoot, 'app_api.py'))) {
  throw new Error(`Invoice Downloader source is unavailable at ${sourceRoot}`)
}
if (!existsSync(join(sourceRoot, 'local_recognition.py'))) {
  throw new Error(`local recognition engine is unavailable at ${sourceRoot}`)
}
for (const required of [
  'brand_generated.py',
  'expense_rules/__init__.py',
  'builtin/categories.yaml',
]) {
  if (!existsSync(join(sourceRoot, required))) {
    throw new Error(`classification rules source is unavailable at ${sourceRoot}/${required}`)
  }
}

rmSync(engineRoot, { recursive: true, force: true })
mkdirSync(join(engineRoot, 'src', 'invoice_engine'), { recursive: true })

for (const file of engineSourceFiles) {
  copyFile(join(sourceRoot, file), join(engineRoot, 'src', 'invoice_engine', file))
}

const engineDataFiles = ['builtin/categories.yaml']
for (const file of engineDataFiles) {
  copyFile(join(sourceRoot, file), join(engineRoot, 'src', 'invoice_engine', file))
}

copyFile(
  join(packageRoot, 'engine-adapter', 'ipc', 'protocol.py'),
  join(engineRoot, 'src', 'invoice_engine', 'ipc', 'protocol.py'),
)
writeFileSync(join(engineRoot, 'src', 'invoice_engine', '__init__.py'), '"""Bundled Invoice Downloader engine source."""\n')

const sourceSha = execFileSync('git', ['-C', sourceRoot, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
writeFileSync(
  join(engineRoot, 'MANIFEST.json'),
  `${JSON.stringify({
    sourceRepository: 'https://github.com/woniu-zk/tidyinvoice',
    sourceSha,
    generatedBy: '@woniu-zk/dsh-invoice-downloader',
    generatedAt: new Date().toISOString(),
    sourceFiles: [...engineSourceFiles, 'ipc/protocol.py'].sort(),
    dataFiles: engineDataFiles,
  }, null, 2)}\n`,
)
