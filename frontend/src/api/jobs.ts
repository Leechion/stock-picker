import client from './client'
import type { Job } from '@/types/monitor'

/**
 * Long pipelines (factor computation, ranking, full sync) run as background
 * jobs. `startJob` returns as soon as the job is queued — it does NOT wait for
 * the pipeline to finish, which previously took ~16 minutes and blew past the
 * axios timeout.
 */
export function startJob(
  jobType: string,
  params: { trading_date?: string; concurrency?: number } = {}
) {
  return client.post(`/jobs/${jobType}`, null, { params })
}

export function getJob(jobId: number) {
  return client.get(`/jobs/${jobId}`)
}

export function listJobs(jobType?: string, limit = 20) {
  return client.get('/jobs/', { params: { job_type: jobType, limit } })
}

export function cancelJob(jobId: number) {
  return client.post(`/jobs/${jobId}/cancel`)
}

/** Convenience: launch the full factor → ranking → alert pipeline. */
export function startFullRanking(concurrency = 12) {
  return startJob('full_ranking', { concurrency })
}

/**
 * Poll a job until it reaches a terminal state.
 *
 * Used as a fallback for environments where the WebSocket is unavailable.
 * `onProgress` is called on every poll so the UI can still show a bar.
 */
export async function pollJobUntilDone(
  jobId: number,
  onProgress?: (job: Job) => void,
  intervalMs = 1500
): Promise<Job> {
  const terminal = new Set(['succeeded', 'failed', 'cancelled'])
  for (;;) {
    const { data } = await getJob(jobId)
    const job = data as Job
    onProgress?.(job)
    if (terminal.has(job.status)) return job
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}
