/**
 * Public dashboard — the landing experience for every visitor.
 *
 * It renders immediately, with no sign-in required, and explains what AQG does.
 * Actions that need an account are ordinary hash links: the router guard opens
 * the sign-in modal and resumes the intended feature afterwards. All platform
 * facts shown here come from the public `/api/status` payload (never invented
 * usage statistics or testimonials).
 */

import { getStatus } from '../api.js';
import { escapeHtml, hydrateIcons } from '../dom.js';
import { icon } from '../icons.js';

/** The seven headline capabilities, each with an action that leads to it. */
const FEATURES = [
  {
    icon: 'sparkle',
    title: 'AI Question Generation',
    text: 'Turn any chapter or paper into grounded questions — multiple choice, true/false, short answer, essay and more — written only from your document.',
    action: { label: 'Generate questions', href: '#/generate' },
  },
  {
    icon: 'scenario',
    title: 'Scenario-Based Questions',
    text: 'Apply concepts to realistic situations so learners practise reasoning and decision-making, not just recall.',
    action: { label: 'Create scenario questions', href: '#/generate?type=scenario' },
  },
  {
    icon: 'book',
    title: 'Case Study Generation',
    text: 'Build structured case studies with sub-questions and marking criteria, retrieved from the passages that matter.',
    action: { label: 'Generate a case study', href: '#/generate?type=case-study' },
  },
  {
    icon: 'summary',
    title: 'Study Summaries',
    text: 'Distil long material into concise summaries, key concepts, definitions and revision notes you can review quickly.',
    action: { label: 'Create a summary', href: '#/study?type=summary' },
  },
  {
    icon: 'cards',
    title: 'Flashcard Generation',
    text: 'Produce ready-to-drill flashcards that target the precise terminology and ideas in your learning material.',
    action: { label: 'Create flashcards', href: '#/study?type=flashcards' },
  },
  {
    icon: 'assessment',
    title: 'Interactive Assessments',
    text: 'Take auto-graded assessments in the browser with instant feedback, explanations and partial credit for written answers.',
    action: { label: 'Open assessments', href: '#/assessments' },
  },
  {
    icon: 'trending',
    title: 'Performance Tracking',
    text: 'Follow real averages, score bands and topic-level strengths across every attempt so you always know what to review next.',
    action: { label: 'View performance', href: '#/performance' },
  },
];

/** The five-step workflow, kept in the order the product actually runs. */
const STEPS = [
  {
    title: 'Upload your learning material',
    text: 'Add a PDF or text document — a lecture, chapter, report or set of notes.',
  },
  {
    title: 'Choose a study or assessment activity',
    text: 'Pick a question format, difficulty, count or a study resource such as a summary or flashcards.',
  },
  {
    title: 'AI retrieves the relevant information',
    text: 'Retrieval-augmented generation selects the passages that actually support each item before writing.',
  },
  {
    title: 'Generate grounded learning resources',
    text: 'Every question and note is validated and tied to your source, and the answer key stays server-side.',
  },
  {
    title: 'Practise, get feedback and track progress',
    text: 'Submit assessments for automatic scoring, review the explanations and watch your analytics improve.',
  },
];

export default async function render({ query = {} } = {}) {
  // The public status endpoint is safe to call for anonymous visitors.
  const status = await getStatus().catch(() => null);
  const facts = buildFacts(status);

  const content = `
    <section class="pub-hero" id="home">
      <div class="pub-hero__body">
        <span class="pub-hero__eyebrow">
          <span data-icon-slot="sparkle" aria-hidden="true"></span> AI-powered assessment &amp; study
        </span>
        <h1 class="pub-hero__title">Transform Your Learning Materials into Intelligent Study Resources</h1>
        <p class="pub-hero__text">
          Upload your learning documents and use AI to generate quizzes, scenario-based questions,
          case studies, summaries, flashcards, and interactive assessments.
        </p>
        <div class="pub-hero__actions">
          <a class="btn btn--primary btn--lg" href="#/dashboard">
            <span class="btn__icon" data-icon-slot="arrowRight" aria-hidden="true"></span> Get Started
          </a>
          <a class="btn btn--secondary btn--lg" href="#/generate">
            <span class="btn__icon" data-icon-slot="sparkle" aria-hidden="true"></span> Generate Questions
          </a>
          <a class="btn btn--ghost btn--lg" href="#/home?section=features">
            <span class="btn__icon" data-icon-slot="layers" aria-hidden="true"></span> Explore Features
          </a>
        </div>
        ${
          facts.length
            ? `<ul class="pub-hero__facts">${facts
                .map(
                  (fact) => `
              <li>
                <span class="pub-hero__fact-value">${escapeHtml(fact.value)}</span>
                <span class="pub-hero__fact-label">${escapeHtml(fact.label)}</span>
              </li>`,
                )
                .join('')}</ul>`
            : ''
        }
      </div>
      <aside class="pub-hero__aside" data-rail aria-label="What signing in unlocks">
        <div class="pub-hero__panel">
          <p class="pub-hero__panel-title">Explore freely. Sign in when you create.</p>
          <p class="pub-hero__panel-text">
            Browse the platform without an account. When you upload a document or generate study
            material, AQG asks you to continue with Google — then takes you straight to that feature.
          </p>
          <ul class="pub-hero__panel-list">
            <li><span data-icon-slot="shield" aria-hidden="true"></span> Your material stays private to your account</li>
            <li><span data-icon-slot="sparkle" aria-hidden="true"></span> Questions grounded in your source, every time</li>
            <li><span data-icon-slot="trending" aria-hidden="true"></span> Progress tracked across every attempt</li>
          </ul>
        </div>
      </aside>
    </section>

    <section class="pub-section" id="features" aria-labelledby="features-title">
      <div class="pub-section__header">
        <p class="pub-section__eyebrow">Features</p>
        <h2 class="pub-section__title" id="features-title">Everything you need to study from your own material</h2>
        <p class="pub-section__text">
          Start anywhere. Each capability is grounded in the document you provide, and any action
          that creates content will ask you to sign in first.
        </p>
      </div>
      <div class="feature-grid">
        ${FEATURES.map(featureCard).join('')}
      </div>
    </section>

    <section class="pub-section" id="how" aria-labelledby="how-title">
      <div class="pub-section__header">
        <p class="pub-section__eyebrow">How It Works</p>
        <h2 class="pub-section__title" id="how-title">From document to mastery in five steps</h2>
      </div>
      <ol class="steps">
        ${STEPS.map(
          (step, index) => `
          <li class="step">
            <span class="step__index">${index + 1}</span>
            <div class="step__body">
              <p class="step__title">${escapeHtml(step.title)}</p>
              <p class="step__text">${escapeHtml(step.text)}</p>
            </div>
          </li>`,
        ).join('')}
      </ol>
    </section>

    <section class="pub-section" id="about" aria-labelledby="about-title">
      <div class="about-grid">
        <div>
          <p class="pub-section__eyebrow">About AQG</p>
          <h2 class="pub-section__title" id="about-title">Assessment you can trust, built on retrieval-augmented generation</h2>
          <p class="pub-section__text">
            AQG — the Automated Question Generation system — is an educational assessment and study
            platform. It reads the documents you upload, retrieves the passages that matter and uses
            them to write questions, case studies, summaries and flashcards. Because everything is
            grounded in your own material, the output stays accurate and on-topic.
          </p>
          <p class="pub-section__text">
            Written answers are graded server-side with partial credit, the answer key is never sent
            to the browser before you submit, and your documents and results remain private to your
            account. There are no invented statistics here — once you are signed in, every number you
            see comes from your own activity.
          </p>
        </div>
        <ul class="about-points">
          <li><span data-icon-slot="layers" aria-hidden="true"></span><div><strong>Grounded by design</strong><p>Every item traces back to retrieved passages from your document.</p></div></li>
          <li><span data-icon-slot="shield" aria-hidden="true"></span><div><strong>Private to you</strong><p>Uploads, generated resources and results are scoped to your account.</p></div></li>
          <li><span data-icon-slot="target" aria-hidden="true"></span><div><strong>Honest analytics</strong><p>Performance charts are computed only from your real attempts.</p></div></li>
        </ul>
      </div>
    </section>

    <section class="pub-cta" aria-labelledby="cta-title">
      <div>
        <h2 class="pub-cta__title" id="cta-title">Ready to turn a document into a study session?</h2>
        <p class="pub-cta__text">Sign in with Google and generate your first assessment in minutes.</p>
      </div>
      <div class="pub-cta__actions">
        <a class="btn btn--primary btn--lg" href="#/dashboard">Get Started</a>
        <a class="btn btn--secondary btn--lg" href="#/generate">Generate Questions</a>
      </div>
    </section>`;

  return {
    title: 'Welcome to AQG',
    breadcrumb: 'AI-powered assessment & study',
    content,
    mount(root) {
      hydrateIcons(root, icon);
      scrollToRequestedSection(root, query.section);
    },
  };
}

/** Builds the small row of real platform facts shown under the hero. */
function buildFacts(status) {
  if (!status) return [];
  const facts = [];
  const questionTypes = Array.isArray(status.question_types) ? status.question_types.length : 0;
  const studyTypes = Array.isArray(status.study_material_types) ? status.study_material_types.length : 0;
  const limits = status.limits || {};

  if (questionTypes) facts.push({ value: String(questionTypes), label: 'Question formats' });
  if (studyTypes) facts.push({ value: String(studyTypes), label: 'Study resource types' });
  if (limits.max_upload_mb) facts.push({ value: `${limits.max_upload_mb} MB`, label: 'Max upload size' });
  if (Array.isArray(limits.allowed_extensions) && limits.allowed_extensions.length) {
    facts.push({
      value: limits.allowed_extensions.map((ext) => String(ext).replace('.', '').toUpperCase()).join(' & '),
      label: 'Supported documents',
    });
  }
  return facts;
}

/** One interactive capability card with its action link. */
function featureCard(feature) {
  return `
    <article class="feature-card">
      <span class="feature-card__icon" data-icon-slot="${escapeHtml(feature.icon)}" aria-hidden="true"></span>
      <h3 class="feature-card__title">${escapeHtml(feature.title)}</h3>
      <p class="feature-card__text">${escapeHtml(feature.text)}</p>
      <a class="feature-card__action" href="${escapeHtml(feature.action.href)}">
        <span>${escapeHtml(feature.action.label)}</span>
        <span data-icon-slot="arrowRight" aria-hidden="true"></span>
      </a>
    </article>`;
}

/** Scrolls to a section requested via `#/home?section=...`. */
function scrollToRequestedSection(root, section) {
  if (!section) return;
  const target = root.querySelector(`#${section}`);
  if (!target) return;
  window.requestAnimationFrame(() => {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}
