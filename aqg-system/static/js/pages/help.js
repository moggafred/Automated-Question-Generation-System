/**
 * Help: how the platform works, from upload to performance analytics.
 */

import { getStatus } from '../api.js';
import { escapeHtml, hydrateIcons } from '../dom.js';
import { icon } from '../icons.js';
import { getLimits } from '../store.js';

const STEPS = [
  {
    icon: 'upload',
    title: 'Upload your material',
    body: 'Drop in a PDF or TXT of lecture notes, a chapter or an article. The text is extracted, split into overlapping chunks and indexed for retrieval.',
  },
  {
    icon: 'search',
    title: 'Retrieve the relevant passages',
    body: 'A topic focus narrows retrieval with TF-IDF scoring over word and bigram features. With no topic, the most representative chunks are used.',
  },
  {
    icon: 'sparkle',
    title: 'Generate and validate',
    body: 'The AI writes questions only from the retrieved passages. Every item is then checked for structure, option integrity, duplication and answerability before you ever see it.',
  },
  {
    icon: 'shield',
    title: 'Take the assessment',
    body: 'The answer key stays on the server. The browser never receives it, so answers cannot be read off the network tab before you submit.',
  },
  {
    icon: 'checkCircle',
    title: 'Automatic grading',
    body: 'Choice questions are matched against the answer key. Written answers earn partial credit based on how much of the key idea they contain.',
  },
  {
    icon: 'trending',
    title: 'Track real progress',
    body: 'Every attempt is stored. Performance analytics aggregate those rows, so no score on this platform is ever fabricated.',
  },
];

const FAQ = [
  {
    q: 'Which file types work?',
    a: 'PDF and plain text. A scanned or image-only PDF contains no readable text until it has been through OCR, so generation will report that it could not find text.',
  },
  {
    q: 'Why do my questions look similar to the document?',
    a: 'That is intentional. Every question is written from retrieved passages and carries a reference to the source it came from, so you always know where the content originated.',
  },
  {
    q: 'How is written-answer grading decided?',
    a: 'The response is normalised and compared with the expected answer. Overlap with key terms earns partial marks, so a partly correct answer is not scored as zero.',
  },
  {
    q: 'Can I retake the same assessment?',
    a: 'Yes. Open it from History and submit again. Each submission is recorded as a separate attempt and all of them count towards your analytics.',
  },
  {
    q: 'Is my data sent anywhere else?',
    a: 'Documents and results are written to a local SQLite database in the project directory. The only external call is the AI provider configured through environment variables.',
  },
  {
    q: 'Why did generation fail?',
    a: 'Usually one of three things: the file had no readable text, the AI provider is not configured, or the response failed validation. The error message on screen names the cause.',
  },
];

export default async function render() {
  let status = null;
  try {
    status = await getStatus();
  } catch {
    status = null;
  }

  const limits = getLimits();

  const content = `
    <div class="page__header">
      <h1 class="page__title">How AQG works</h1>
      <p class="page__subtitle">
        A retrieval-augmented assessment platform: your document is the only source of truth, and
        every score you see comes from a real, stored attempt.
      </p>
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">The pipeline</h2>
          <p class="card__subtitle">Six steps from upload to insight</p>
        </div>
      </div>
      <div class="card__body">
        <div class="concept-grid">
          ${STEPS.map(
            (step, index) => `
            <div class="concept-card">
              <span class="stat__icon" data-icon-slot="${escapeHtml(step.icon)}" style="margin-bottom:var(--space-3)"></span>
              <p class="concept-card__title">${index + 1}. ${escapeHtml(step.title)}</p>
              <p class="concept-card__body">${escapeHtml(step.body)}</p>
            </div>`,
          ).join('')}
        </div>
      </div>
    </section>

    <div class="split split--sidebar">
      <section class="card">
        <div class="card__header">
          <div>
            <h2 class="card__title">Question formats</h2>
            <p class="card__subtitle">What each format asks of you</p>
          </div>
        </div>
        <div class="card__body">
          <div class="definition-list">
            ${formatRow('multiple-choice', 'Choose one of four or more options. Graded exactly.')}
            ${formatRow('true-false', 'A single true or false judgement. Fastest way to reinforce facts.')}
            ${formatRow('short-answer', 'Recall a definition or explanation in your own words.')}
            ${formatRow('fill-in-the-blank', 'Supply the missing term. Targets precise vocabulary.')}
            ${formatRow('essay', 'An extended written response with marking guidance and partial credit.')}
            ${formatRow('scenario-based', 'A realistic situation presented before the question, then applied knowledge.')}
            ${formatRow('case-study', 'One grounded case narrative followed by several sub-questions.')}
            ${formatRow('application', 'Use the material to solve a practical problem.')}
            ${formatRow('mixed', 'A balanced combination of every format above.')}
          </div>
        </div>
      </section>

      <section class="card" data-rail>
        <div class="card__header"><h2 class="card__title">Study resources</h2></div>
        <div class="card__body">
          <ul class="bullet-list">
            <li class="bullet-list__item">
              <span class="bullet-list__marker" data-icon-slot="summary" style="display:flex"></span>
              <span><strong>Summary</strong> &mdash; overview, key points and learning outcomes</span>
            </li>
            <li class="bullet-list__item">
              <span class="bullet-list__marker" data-icon-slot="layers" style="display:flex"></span>
              <span><strong>Key concepts</strong> &mdash; named ideas and why they matter</span>
            </li>
            <li class="bullet-list__item">
              <span class="bullet-list__marker" data-icon-slot="cards" style="display:flex"></span>
              <span><strong>Flashcards</strong> &mdash; flippable cards for active recall</span>
            </li>
            <li class="bullet-list__item">
              <span class="bullet-list__marker" data-icon-slot="book" style="display:flex"></span>
              <span><strong>Definitions</strong> &mdash; glossary entries with examples</span>
            </li>
            <li class="bullet-list__item">
              <span class="bullet-list__marker" data-icon-slot="fileText" style="display:flex"></span>
              <span><strong>Revision notes</strong> &mdash; structured blocks with key takeaways</span>
            </li>
          </ul>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Frequently asked</h2>
          <p class="card__subtitle">Common questions about behaviour and limits</p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="record-list">
          ${FAQ.map(
            (item) => `
            <div class="review-item">
              <p class="review-item__prompt">${escapeHtml(item.q)}</p>
              <p class="prose-block__text">${escapeHtml(item.a)}</p>
            </div>`,
          ).join('')}
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card__header"><h2 class="card__title">Running your own instance</h2></div>
      <div class="card__body">
        <div class="prose-block">
          <p class="prose-block__text">
            This project runs with a single command. Copy the example environment file, add your
            AI provider key, then start the server.
          </p>
          <div class="alert alert--info">
            <span class="alert__icon" data-icon-slot="externalLink"></span>
            <div class="alert__body">
              <p class="alert__title">Quick start</p>
              <p class="prose-block__text" style="margin-top:var(--space-2)">
                <span class="mono">cp .env.example .env</span><br />
                <span class="mono">pip install -r requirements.txt</span><br />
                <span class="mono">uvicorn main:app --reload</span>
              </p>
            </div>
          </div>
          ${
            status
              ? `<div class="settings-group">
                   ${row('Version', status.version)}
                   ${row('Environment', status.environment)}
                   ${row('AI provider', `${status.services?.llm?.provider} · ${status.services?.llm?.status}`)}
                   ${row('Upload limit', `${limits.maxUploadMb}MB`)}
                 </div>`
              : ''
          }
        </div>
      </div>
    </section>`;

  return {
    title: 'Help & Guide',
    breadcrumb: 'How the platform works',
    content,
    mount(root) {
      hydrateIcons(root, icon);
    },
  };
}

/** Rendered by the router for any hash that matches no route. */
export function notFoundView(path) {
  return `
    <div class="page__header">
      <h1 class="page__title">Page not found</h1>
      <p class="page__subtitle">
        Nothing is routed at <span class="mono">${escapeHtml(path)}</span>.
      </p>
    </div>
    <section class="card">
      <div class="card__body">
        <div class="state">
          <span class="state__icon" data-icon-slot="search"></span>
          <p class="state__title">That link does not lead anywhere</p>
          <p class="state__text">It may be an old link from a previous version of the app.</p>
          <a class="btn btn--primary" href="#/dashboard">Back to the dashboard</a>
        </div>
      </div>
    </section>`;
}

function formatRow(value, description) {
  return `
    <div class="definition-item">
      <p class="definition-item__term">${escapeHtml(value)}</p>
      <p class="definition-item__body">${escapeHtml(description)}</p>
    </div>`;
}

function row(label, value) {
  return `
    <div class="settings-row">
      <span class="settings-row__label">${escapeHtml(label)}</span>
      <span class="settings-row__value">${escapeHtml(String(value ?? '—'))}</span>
    </div>`;
}