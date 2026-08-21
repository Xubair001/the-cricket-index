import { PageHeader, Panel, SectionHeading } from '../components/ui'

/**
 * About and contact.
 *
 * Also the one place the data attribution lives. It used to sit in the global
 * footer on every screen, which read as a disclaimer stapled to the product; but
 * it cannot simply be deleted, because the match data is published under
 * ODC-BY 1.0 and that licence REQUIRES attribution. Moving it here satisfies the
 * licence and keeps it off every page.
 *
 * Deliberately plain about what the product is and is not, in the same terms the
 * rest of it uses: derived figures are computed here, official ratings are shown
 * as published, and the two are never merged.
 */
export function Contact() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="The Cricket Index"
        title="About and contact"
        blurb="A decision-support platform for cricket: who to pick, and why. Built on ball-by-ball records, with the workings shown for every figure."
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Get in touch"
          blurb="Questions, corrections, or access for your team or league."
        >
          <dl className="space-y-4">
            <div>
              <dt className="u-eyebrow">Email</dt>
              <dd className="mt-1">
                <a
                  href="mailto:abdullahzubair356@gmail.com"
                  className="text-sm font-medium text-analytic-ink hover:underline"
                >
                  abdullahzubair356@gmail.com
                </a>
              </dd>
            </div>
            <div>
              <dt className="u-eyebrow">Phone</dt>
              <dd className="mt-1">
                {/* tel: with the full international form, so it dials from a
                    handset without the reader having to reformat it. */}
                <a
                  href="tel:+923120321939"
                  className="tnum text-sm font-medium text-analytic-ink hover:underline"
                >
                  +92 312 032 1939
                </a>
              </dd>
            </div>
            <div>
              <dt className="u-eyebrow">Maintained by</dt>
              <dd className="mt-1 text-sm text-ink">Abdullah Zubair</dd>
            </div>
          </dl>
        </Panel>

        <Panel
          title="What this is"
          blurb="And, as importantly, what it is not."
        >
          <ul className="space-y-2.5 text-sm leading-relaxed text-muted">
            <li>
              <span className="font-medium text-ink">It answers selection questions.</span> Who is
              in form, who fits a brief, who belongs in a side, and what that side cost.
            </li>
            <li>
              <span className="font-medium text-ink">Every figure shows its workings.</span> A
              rating carries its components; a filter that cannot be honoured says so on screen
              rather than being dropped.
            </li>
            <li>
              <span className="font-medium text-ink">It is not a live-score service.</span> No
              in-play scores, no commentary, no fantasy.
            </li>
            <li>
              <span className="font-medium text-ink">
                Computed figures and official ratings stay apart.
              </span>{' '}
              Ratings published by the ICC are shown exactly as published and are never blended
              with anything derived here.
            </li>
          </ul>
        </Panel>
      </div>

      <SectionHeading
        title="Data and attribution"
        note="Where the underlying records come from, and the terms they carry."
      />

      <Panel title="Sources">
        <div className="space-y-3 text-sm leading-relaxed text-muted">
          <p>
            Ball-by-ball match records are used under the{' '}
            <a
              href="https://opendatacommons.org/licenses/by/1-0/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-analytic-ink hover:underline"
            >
              Open Data Commons Attribution Licence (ODC-BY 1.0)
            </a>
            , which requires this attribution:{' '}
            <a
              href="https://cricsheet.org"
              target="_blank"
              rel="noopener noreferrer"
              className="text-analytic-ink hover:underline"
            >
              Cricsheet.org
            </a>
            . Official player and team ratings, the fixture calendar and squad announcements come
            from the International Cricket Council.
          </p>
          <p>
            Every other figure on this site is computed here from those records. None of it is an
            official rating, and nothing derived is ever presented as one.
          </p>
          <p>
            Headlines in the press section are linked to their publishers and remain the property of
            those publishers. Nothing in that section feeds any figure elsewhere on the site.
          </p>
        </div>
      </Panel>

      <p className="text-xs text-dim">
        &copy; {new Date().getFullYear()} The Cricket Index. All rights reserved. Analysis and
        derived figures are the work of this project.
      </p>
    </div>
  )
}

export default Contact
