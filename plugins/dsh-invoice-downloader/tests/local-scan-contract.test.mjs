import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Readable } from 'node:stream'
import test from 'node:test'

const packageRoot = join(import.meta.dirname, '..')
const read = (...parts) => readFileSync(join(packageRoot, ...parts), 'utf8')

const scannerSource = read('src', 'invoice-scanner.ts')
const ipcClientSource = read('src', 'ipc-client.ts')
const rpcHandlerSource = read('src', 'rpc-handler.ts')
const storageSource = read('src', 'storage.ts')
const scanAdapter = read('engine-adapter', 'dsh_scan.py')
const runnerAdapter = read('engine-adapter', 'dsh_runner.py')

const legacyModelRecognition = /recognition_chain|RecognitionChain|deepseek_extractor|DeepSeekExtractor|glm_fallback|create_glm_fallback|DeepSeekExtractor|GLM_API_KEY/i

test('the shipped plugin carries no model-recognition bridge', () => {
  for (const [name, source] of [
    ['invoice-scanner.ts', scannerSource],
    ['ipc-client.ts', ipcClientSource],
    ['rpc-handler.ts', rpcHandlerSource],
    ['dsh_scan.py', scanAdapter],
    ['dsh_runner.py', runnerAdapter],
  ]) {
    assert.doesNotMatch(source, legacyModelRecognition, `${name} must not reference the legacy model chain`)
  }
  assert.doesNotMatch(scannerSource, /@deepseek-ai\/dsh-llm/)
  assert.doesNotMatch(scannerSource, /prepareCall|TextResponseAssembler|extractWithModel|llmContext/)
  assert.doesNotMatch(ipcClientSource, /extraction\.(request|response|error)|onExtraction|respondToExtraction/)
  assert.doesNotMatch(rpcHandlerSource, /hasGlmApiKey|ocrProvider|glmApiKey/)
  assert.doesNotMatch(storageSource, /logModelVisible|createInvoiceUserMessage|ModelVisibleEvent/)
})

test('the engine adapter routes every scan through LocalRecognitionWorker', () => {
  assert.match(scanAdapter, /from local_recognition import LocalRecognitionWorker/)
  assert.match(scanAdapter, /_worker_extractor_factory=lambda _runtime: LocalRecognitionWorker\(/)
  assert.doesNotMatch(scanAdapter, /^\s*(from|import)\s+(recognition_chain|deepseek_extractor|glm_fallback|local_ocr)\b/m)
  assert.doesNotMatch(runnerAdapter, /^\s*(from|import)\s+(recognition_chain|deepseek_extractor|glm_fallback|local_ocr)\b/m)
  assert.match(runnerAdapter, /result = run_scan\(config=config\)/)
})

test('scan job payload carries only mailbox and output settings', async () => {
  const writes = []
  const stdout = Readable.from([
    '{"type":"job.result","result":{"status":"completed","invoicesProcessed":2,"successCount":1,"retainedCount":0,"manualReviewCount":0}}\n',
  ])
  const handle = {
    pid: 7,
    stdin: { write(chunk) { writes.push(chunk) } },
    stdout,
    stderr: Readable.from([]),
    done: Promise.resolve({ exitCode: 0, signal: null }),
    terminate() {},
  }
  const { InvoiceScanner } = await import('../lib/invoice-scanner.js')
  const scanner = new InvoiceScanner({ spawn() { return handle } }, {
    pythonPath: 'fixture-python',
    engineRoot: 'fixture-engine',
    adapterRoot: 'fixture-adapter',
    deadlineMs: 1_000,
    graceMs: 1,
    imapFetchTimeoutSeconds: 15,
  })
  const result = await scanner.startScan({
    jobId: 'fixture-job',
    email: 'fixture@qq.com',
    authCode: 'fixture-auth-code',
    dateFrom: '2026-01-01',
    dateTo: '2026-01-02',
    company: 'Fixture',
    savePath: 'C:/fixture-output',
  })
  assert.deepEqual(result, {
    status: 'completed',
    invoicesProcessed: 2,
    successCount: 1,
    retainedCount: 0,
    manualReviewCount: 0,
  })
  assert.equal(writes.length, 1)
  const jobConfig = JSON.parse(writes[0])
  assert.deepEqual(Object.keys(jobConfig).sort(), [
    'authCode',
    'company',
    'dateFrom',
    'dateTo',
    'email',
    'imapFetchTimeoutSeconds',
    'jobId',
    'protocolVersion',
    'savePath',
    'timestamp',
    'type',
  ])
  assert.equal(jobConfig.glmApiKey, undefined)
  assert.equal(jobConfig.ocrProvider, undefined)
  assert.equal(jobConfig.apiKey, undefined)
})
