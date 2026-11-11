import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://bibigurl-yum.github.io',
  base: '/Hookshot',
  trailingSlash: 'always',
  integrations: [starlight({
    title: 'Hookshot',
    description: 'The community field guide to Hookshot. Install, explore settings, find answers, and contribute.',
    favicon: '/assets/hookshot.png',
    customCss: ['./src/styles/forest.css'],
    components: {
      Header: './src/components/Header.astro',
      Hero: './src/components/Hero.astro',
      Footer: './src/components/Footer.astro',
    },
    editLink: { baseUrl: 'https://github.com/bibigurl-yum/Hookshot/edit/docs/starlight-preview/' },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 2 },
    sidebar: [
      { label: 'The field guide', slug: '' },
      { label: 'Begin your adventure', items: [
        { label: 'Getting started', slug: 'guides/getting-started' },
        { label: 'Graphics & controls', slug: 'guides/graphics-and-controls' },
        { label: 'Updates & saves', slug: 'guides/updates-and-saves' },
        { label: 'Transfer a save', slug: 'guides/saves' },
      ] },
      { label: 'Find your way', items: [
        { label: 'Common issues', slug: 'guides/common-issues', badge: { text: '11 answers', variant: 'note' } },
        { label: 'Report & contribute', slug: 'guides/reporting-and-contributing' },
        { label: 'Report a bug ↗', link: 'https://github.com/NotRexed/Hookshot/issues/new/choose' },
      ] },
      { label: 'Under the hood', collapsed: true, items: [
        { label: 'Reference manual', slug: 'reference/manual' },
        { label: 'Development', slug: 'guides/development' },
        { label: 'Architecture', slug: 'guides/design' },
        { label: 'Contributing', slug: 'reference/contributing' },
        { label: 'Technical notes', slug: 'guides/technical-notes' },
        { label: 'Versioning', slug: 'guides/versioning' },
        { label: 'Workflow', slug: 'guides/workflow' },
        { label: 'Pipeline lists', slug: 'reference/pipeline-states' },
      ] },
      { label: 'About the preview', slug: 'about' },
    ],
  })],
});
