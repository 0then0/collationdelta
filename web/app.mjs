import { read, validate, EXPORT_LIMIT, DEADLINE_MS } from './input.mjs';
const $ = (id) => document.getElementById(id);
let revision = 0,
  active = null,
  timer = null,
  downloadURL = null,
  inputs = null;
function message(text, state = 'neutral') {
  $('status').textContent = text;
  $('status').dataset.state = state;
}
function invalidate() {
  revision++;
  active?.terminate();
  active = null;
  clearTimeout(timer);
  if (downloadURL) URL.revokeObjectURL(downloadURL);
  downloadURL = null;
  inputs = null;
  $('download').hidden = true;
  $('details').hidden = true;
  $('capture').disabled = true;
  $('cancel').disabled = true;
  $('summary').textContent = 'Choose both files or load the example.';
  message('No capture available.');
  return revision;
}
function ready(corpus, requested, token) {
  if (token !== revision) return;
  validate(corpus, requested);
  inputs = { corpus, requested };
  $('summary').textContent =
    `${corpus.entries.length} strings · ${corpus.entries.length ** 2} ordered pairs\nLocale: ${JSON.stringify(requested.locale)}\nOptions: ${JSON.stringify(requested.options, null, 2)}`;
  $('capture').disabled = false;
  message('Inputs validated. Ready to capture.');
}
async function filesChanged() {
  const token = invalidate();
  if (!$('corpus').files.length || !$('profile').files.length) return;
  message('Reading inputs…');
  try {
    const [corpus, requested] = await Promise.all([
      read($('corpus').files[0]),
      read($('profile').files[0]),
    ]);
    ready(corpus, requested, token);
  } catch (error) {
    if (token === revision) message(error.message, 'error');
  }
}
$('corpus').addEventListener('change', filesChanged);
$('profile').addEventListener('change', filesChanged);
$('label').addEventListener('input', () => {
  const snapshot = inputs;
  const token = invalidate();
  if (snapshot) ready(snapshot.corpus, snapshot.requested, token);
  else filesChanged();
});
$('example').addEventListener('click', () => {
  const token = invalidate();
  $('corpus').value = '';
  $('profile').value = '';
  // Same small inputs as examples/browser-page; no network or file preprocessing.
  ready(
    {
      version: 1,
      entries: [
        { id: 'empty', value: '' },
        { id: 'upper', value: 'A' },
        { id: 'lower', value: 'a' },
        { id: 'combining', value: 'e\u0301' },
        { id: 'composed', value: 'é' },
        { id: 'supplementary', value: '😀' },
        { id: 'control', value: '\u0000\n' },
        { id: 'duplicate', value: 'A' },
      ],
    },
    { version: 1, contract: 'intl.collator.v1', locale: 'en', options: { sensitivity: 'base' } },
    token,
  );
});
$('cancel').addEventListener('click', () => {
  invalidate();
  message('Capture cancelled. Select inputs again.');
});
$('capture').addEventListener('click', () => {
  if (!inputs || active) return;
  const snapshot = inputs;
  const token = ++revision;
  $('capture').disabled = true;
  $('cancel').disabled = false;
  $('download').hidden = true;
  $('details').hidden = true;
  if (downloadURL) URL.revokeObjectURL(downloadURL);
  downloadURL = null;
  message('Capturing in this browser’s Dedicated Worker…');
  function fail(reason) {
    if (token !== revision) return;
    revision++;
    active?.terminate();
    active = null;
    clearTimeout(timer);
    $('cancel').disabled = true;
    $('capture').disabled = false;
    message(reason, 'error');
  }
  try {
    active = new Worker(new URL('./worker.mjs', import.meta.url), { type: 'module' });
    timer = setTimeout(
      () => fail('Capture exceeded 15 seconds. No partial export was saved.'),
      DEADLINE_MS,
    );
    active.onerror = (event) => {
      event.preventDefault();
      fail(
        'Worker failed. No export is available. Check browser support and serve this page over HTTP.',
      );
    };
    active.onmessage = ({ data }) => {
      if (token !== revision) return;
      if (data.error) {
        fail(data.error);
        return;
      }
      active.terminate();
      active = null;
      clearTimeout(timer);
      const value = data.value;
      const blob = new Blob([JSON.stringify(value)], { type: 'application/json' });
      if (blob.size > EXPORT_LIMIT) {
        fail('Export exceeds 16 MiB.');
        return;
      }
      downloadURL = URL.createObjectURL(blob);
      $('download').href = downloadURL;
      $('download').hidden = false;
      $('cancel').disabled = true;
      $('capture').disabled = false;
      $('details').hidden = false;
      $('metadata').textContent = JSON.stringify(
        {
          coverage: value.coverage,
          supportedLocalesOf: value.observation.runtime.intl.supported_locales,
          canonicalLocale: value.observation.runtime.intl.canonical_locale,
          resolvedOptions: value.observation.effective,
          metadata: value.metadata,
        },
        null,
        2,
      );
      message(
        value.observation.status === 'unsupported'
          ? `Unsupported: ${value.observation.reason} No comparisons; export is available for import as incomplete evidence.`
          : value.coverage.complete
            ? 'Observation complete. Download the export, then validate it with import-browser.'
            : 'Observation incomplete: comparison errors occurred. Export includes failures.',
        value.observation.status === 'unsupported'
          ? 'unsupported'
          : value.coverage.complete
            ? 'success'
            : 'error',
      );
    };
    active.postMessage({ ...snapshot, label: $('label').value });
  } catch (error) {
    fail(error.message);
  }
});
