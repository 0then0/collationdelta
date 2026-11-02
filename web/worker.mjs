import { observeIntl } from './intl.mjs';
import { validate, bytes, EXPORT_LIMIT } from './input.mjs';

self.onmessage = ({ data }) => {
  try {
    if (
      !(self instanceof DedicatedWorkerGlobalScope) ||
      typeof document !== 'undefined' ||
      typeof process !== 'undefined'
    )
      throw Error('Expected a browser Dedicated Worker with no document or process.');
    const { corpus, requested, label } = data;
    validate(corpus, requested);
    if (typeof label !== 'string' || [...label].length > 256)
      throw Error('Label exceeds 256 characters.');
    const observation = observeIntl({ protocol_version: 1, corpus, profile: requested });
    for (const result of observation.results) {
      if (result.status === 'ok') result.value = Math.sign(result.value) || 0;
    }
    const expected = corpus.entries.length ** 2;
    const completed = observation.results.filter((r) => r.status === 'ok').length;
    const failed = observation.results.length - completed;
    const complete = observation.status === 'ok' && completed === expected;
    const value = {
      browser_export_version: 1,
      corpus,
      requested,
      observation,
      coverage: {
        entries: corpus.entries.length,
        expected_comparisons: expected,
        completed_comparisons: completed,
        failed_comparisons: failed,
        missing_comparisons: expected - observation.results.length,
        complete,
        consistency: complete ? 'verified' : 'consistent_partial',
      },
      metadata: {
        page_version: 1,
        captured_at: new Date().toISOString(),
        execution_context: { kind: 'dedicated-worker', has_document: false, has_process: false },
        user_agent: navigator.userAgent,
        navigator_platform: navigator.platform,
        caller_labels: { label },
      },
    };
    // The CLI independently verifies consistency; this is a browser observation,
    // not a trusted assertion of consistency or runtime identity.
    if (bytes(value) > EXPORT_LIMIT)
      throw Error('Export exceeds 16 MiB. Use shorter IDs or a smaller corpus.');
    self.postMessage({ value });
  } catch (error) {
    self.postMessage({ error: String(error.message ?? error) });
  }
};
