export interface RunProjection {
  jobId: string
  status: 'active' | 'completed' | 'failed' | 'cancelled'
  startedAt: string
  completedAt?: string
  invoicesProcessed: number
  successCount: number
  retainedCount: number
  manualReviewCount: number
  exportArtifactId?: string
  lastProgress?: string
}

export const PRIVACY_DISCLOSURE = {
  recognition: '发票文件只在本机解析：PDF 文本层直接读取，扫描版 PDF 与图片由本地 OCR 识别，OFD/XML 电子发票直接解析；不需要模型或 API Key，也不会把文件或文本上传到模型或第三方服务。',
  credentials: '邮箱授权码由 DSH 凭据服务管理，不会写入插件设置。',
  localOnly: '此插件只支持运行在本机的 DSH。',
} as const

export class ScanSessionManager {
  private readonly projections = new Map<string, RunProjection>()

  createSession(jobId: string): { jobId: string } {
    this.projections.set(jobId, {
      jobId,
      status: 'active',
      startedAt: new Date().toISOString(),
      invoicesProcessed: 0,
      successCount: 0,
      retainedCount: 0,
      manualReviewCount: 0,
    })
    return { jobId }
  }

  recordProgress(jobId: string, event: string): void {
    const projection = this.projections.get(jobId)
    if (projection) projection.lastProgress = event
  }

  complete(jobId: string, result: {
    invoicesProcessed: number
    successCount: number
    retainedCount: number
    manualReviewCount: number
    exportArtifactId?: string
  }): void {
    const projection = this.projections.get(jobId)
    if (!projection) return
    projection.status = 'completed'
    projection.completedAt = new Date().toISOString()
    projection.invoicesProcessed = result.invoicesProcessed
    projection.successCount = result.successCount
    projection.retainedCount = result.retainedCount
    projection.manualReviewCount = result.manualReviewCount
    projection.exportArtifactId = result.exportArtifactId
  }

  fail(jobId: string): void {
    const projection = this.projections.get(jobId)
    if (!projection) return
    projection.status = 'failed'
    projection.completedAt = new Date().toISOString()
  }

  cancel(jobId: string): void {
    const projection = this.projections.get(jobId)
    if (!projection) return
    projection.status = 'cancelled'
    projection.completedAt = new Date().toISOString()
  }

  getProjection(jobId: string): RunProjection | undefined {
    return this.projections.get(jobId)
  }
}
