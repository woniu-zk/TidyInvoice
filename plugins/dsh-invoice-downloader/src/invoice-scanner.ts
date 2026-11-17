import type { SubprocessRuntime } from '@deepseek-ai/dsh-subprocess'
import {
  EngineIpcClient,
  type JobConfig,
  type JobResult,
} from './ipc-client.js'

export interface InvoiceScannerConfig {
  pythonPath: string
  engineRoot: string
  adapterRoot: string
  deadlineMs: number
  graceMs: number
  imapFetchTimeoutSeconds: number
}

export interface ScanRequest {
  jobId: string
  email: string
  authCode: string
  dateFrom: string
  dateTo: string
  company: string
  savePath: string
}

export interface ScanProgress {
  event: string
}

export interface ScanResult {
  status: 'completed' | 'failed' | 'cancelled'
  invoicesProcessed: number
  successCount: number
  retainedCount: number
  manualReviewCount: number
  exportPath?: string
}

export class InvoiceScanner {
  private client: EngineIpcClient | null = null
  private running = false
  private cancelled = false
  private progressHandler: ((progress: ScanProgress) => void) | null = null

  constructor(
    private readonly subprocess: SubprocessRuntime,
    private readonly config: InvoiceScannerConfig,
  ) {}

  setProgressHandler(handler: (progress: ScanProgress) => void): void {
    this.progressHandler = handler
  }

  get isRunning(): boolean {
    return this.running
  }

  async startScan(request: ScanRequest): Promise<ScanResult> {
    if (this.running) throw new Error('an invoice scan is already running')
    this.running = true
    this.cancelled = false
    this.client = new EngineIpcClient(
      this.subprocess,
      this.config.pythonPath,
      this.config.engineRoot,
      this.config.adapterRoot,
      this.config.graceMs,
    )
    this.client.onEvent(event => this.progressHandler?.({ event: event.event }))

    try {
      const config: JobConfig = {
        jobId: request.jobId,
        email: request.email,
        authCode: request.authCode,
        dateFrom: request.dateFrom,
        dateTo: request.dateTo,
        company: request.company,
        savePath: request.savePath,
        imapFetchTimeoutSeconds: this.config.imapFetchTimeoutSeconds,
      }
      const result = await this.withDeadline(this.client.startJob(config))
      return toScanResult(result)
    } catch {
      if (this.cancelled) return emptyResult('cancelled')
      return emptyResult('failed')
    } finally {
      this.client = null
      this.running = false
    }
  }

  stopScan(): void {
    this.cancelled = true
    this.client?.stopJob()
  }

  private async withDeadline(result: Promise<JobResult>): Promise<JobResult> {
    let timer: NodeJS.Timeout | undefined
    try {
      return await new Promise<JobResult>((resolve, reject) => {
        timer = setTimeout(() => {
          this.client?.stopJob()
          reject(new Error('invoice scan deadline exceeded'))
        }, this.config.deadlineMs)
        void result.then(resolve, reject)
      })
    } finally {
      if (timer) clearTimeout(timer)
    }
  }
}

function toScanResult(result: JobResult): ScanResult {
  return {
    status: 'completed',
    invoicesProcessed: result.invoicesProcessed || 0,
    successCount: result.successCount || 0,
    retainedCount: result.retainedCount || 0,
    manualReviewCount: result.manualReviewCount || 0,
    ...(typeof result.exportPath === 'string' ? { exportPath: result.exportPath } : {}),
  }
}

function emptyResult(status: 'failed' | 'cancelled'): ScanResult {
  return {
    status,
    invoicesProcessed: 0,
    successCount: 0,
    retainedCount: 0,
    manualReviewCount: 0,
  }
}
