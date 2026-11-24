"""The Reality-First Research and Web Research tabs.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

import time
from typing import Any
import streamlit as st

from modules.answer_meta import describe_answer
from modules.behavior_policy import ContentRuleBlocked
from modules.web_research import search_sources_status
from modules.reality_research_agent import CLAIM_CHECK_CAVEAT, ResearchRequest
from ui.shared import get_nexus_core, is_demo_safe, record_perf


def render_reality_research_tab(settings: dict[str, Any]) -> None:
    st.subheader("Reality-First Research Agent")
    st.caption("Search deeply, extract claims, score source trust, detect contradictions, save a grounded report.")
    demo_safe = is_demo_safe(settings)

    query = st.text_area(
        "Research question",
        height=110,
        placeholder="Example: Research this topic deeply and separate confirmed facts from weak leads.",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        depth = st.selectbox("Research depth", ["Quick", "Standard", "Deep", "Extreme"], index=1)
        max_sources = st.slider("Max sources", 5, 150, int(settings.get("reality_research_max_sources", 25)), step=5)
    with col2:
        follow_links = st.checkbox("Follow links", value=bool(settings.get("reality_research_follow_links", True)))
        save_to_memory = st.checkbox("Save to memory", value=True)
    with col3:
        show_weak = st.checkbox("Show weak matches", value=True)
        use_ai_summary = st.checkbox("Provider synthesis", value=True)
        second_opinion = st.checkbox(
            "Model double-checks evidence",
            value=bool(settings.get("reality_research_second_opinion", True)),
            help="When checking a claim, the model also reads each passage counted as supporting it, and the passage "
            "counts only where the model agrees with the wording rules. Adds a few seconds per passage on a CPU.",
        )
        compare_meaning = st.checkbox(
            "Count a story retold in other words once",
            value=bool(settings.get("reality_research_compare_meaning", True)),
            help="When checking a claim, passages from different sites that say the same thing in other words, with "
            "nothing of their own, count as one source: one may be retelling the other. Uses the all-minilm "
            "embedding model in Ollama when it is installed; under a second per check.",
        )

    disabled = not bool(settings.get("enable_reality_research_agent", True))
    if disabled:
        st.info("Reality-First Research Agent is disabled in the sidebar settings.")

    if st.button("Run Reality-First Research", type="primary", disabled=disabled):
        if not query.strip():
            st.warning("Enter a research question first.")
            return
        request = ResearchRequest(
            query=query,
            depth=depth,
            max_sources=int(max_sources),
            follow_links=follow_links,
            save_to_memory=save_to_memory,
            show_weak_matches=show_weak,
            use_ai_summary=use_ai_summary,
            second_opinion=second_opinion,
            compare_meaning=compare_meaning,
            save_report=True,
        )
        progress_lines: list[str] = []
        with st.status("Reality-first research running...", expanded=True) as status:
            def progress(message: str) -> None:
                if message not in progress_lines:
                    progress_lines.append(message)
                    st.write(message)

            started = time.perf_counter()
            try:
                report = get_nexus_core().run_reality_research(
                    request,
                    settings | {"reality_research_depth": depth},
                    progress_callback=progress,
                )
            except ContentRuleBlocked as stopped:
                status.update(label="Not run", state="error")
                st.warning(stopped.reply)
                return
            record_perf("reality_research.run", time.perf_counter() - started, settings)
            status.update(label="Reality-first research complete", state="complete")

        st.session_state.last_reality_research_report = report.to_dict()
        st.markdown("### Final Answer")
        st.markdown(report.final_answer or report.summary)

        if report.verdict:
            st.markdown("### Claim check")
            st.info(f"**{report.verdict}** (evidence: {report.verdict_evidence or 'not rated'}). {report.verdict_why}")
            st.caption(f'Claim checked: "{report.verdict_claim}". {CLAIM_CHECK_CAVEAT}')
            for heading, stance in (("Supporting passages", "supports"), ("Contradicting passages", "contradicts")):
                passages = [item for item in report.claim_evidence if item.stance == stance]
                if passages:
                    st.markdown(f"**{heading}**")
                for item in passages[:5]:
                    dates = "".join(f"; {word} {value[:10]}" for word, value in (("retrieved", item.retrieved_at), ("published", item.published)) if value)
                    st.markdown(f'- "{item.passage}" - [{item.title or item.source or item.url}]({item.url}) (trust: {item.trust_label}{dates})')
                    if item.reason:
                        st.caption(f"Why: {item.reason}" + (" The model agreed." if item.second_opinion == "agrees" else ""))
            set_aside = [item for item in report.claim_evidence if item.stance == "mentions"]
            if set_aside:
                with st.expander(f"Passages that mention the claim without settling it ({len(set_aside)})"):
                    for item in set_aside[:8]:
                        st.markdown(f'- "{item.passage}" - [{item.title or item.source or item.url}]({item.url})')
                        if item.reason:
                            st.caption(f"Why: {item.reason}")
            if report.unaddressed_sources or report.repeated_sources:
                with st.expander(
                    f"Left out: {len(report.unaddressed_sources)} source(s) that did not address the claim, "
                    f"{len(report.repeated_sources)} repeat(s)"
                ):
                    for url in report.unaddressed_sources[:15]:
                        st.markdown(f"- Did not address the claim: {url}")
                    for item in report.repeated_sources[:15]:
                        st.markdown(f"- Counted once ({item['why']}): {item['url']}")
            for note in report.uncertainty_notes:
                st.caption(f"Note: {note}")

        metric_cols = st.columns(5)
        metric_cols[0].metric("Sources", len(report.sources))
        metric_cols[1].metric("Claims", len(report.claims))
        metric_cols[2].metric("Contradictions", len(report.contradictions))
        metric_cols[3].metric("Memory", "Saved" if report.memory_saved else "Not saved")
        metric_cols[4].metric("Errors", len(report.errors))

        if report.saved_paths:
            if demo_safe:
                st.success("Report saved locally. File paths hidden in Demo Safe Mode.")
            else:
                st.success(f"JSON report: {report.saved_paths.get('json')}")
                st.success(f"Markdown report: {report.saved_paths.get('markdown')}")
        if report.errors:
            st.warning("\n".join(report.errors[:8]))

        st.markdown("### Best Sources")
        for source in report.sources[:20]:
            st.markdown(f"**[{source.title or source.url}]({source.url})**")
            st.caption(
                f"{source.source} | {source.source_type} | match {source.match_strength} | "
                f"trust {source.trust_label} ({source.trust_score})"
            )
            st.write(source.excerpt or source.snippet)

        with st.expander("Extracted claims", expanded=False):
            if not report.claims:
                st.info("No factual-looking claims were extracted.")
            for claim in report.claims[:40]:
                st.markdown(f"- **{claim.evidence_strength}** `{claim.claim_type}` {claim.text}")
                st.caption(claim.source_url)

        with st.expander("Potential contradictions", expanded=False):
            if not report.contradictions:
                st.info("No direct contradictions were detected by the lightweight checker.")
            for item in report.contradictions:
                st.warning(f"{item.severity}: {item.reason}")
                st.caption(f"A: {item.claim_a}")
                st.caption(f"B: {item.claim_b}")

        if demo_safe:
            st.caption("Full report JSON hidden in Demo Safe Mode.")
        else:
            with st.expander("Full report JSON", expanded=False):
                st.json(report.to_dict())

    if st.session_state.get("last_reality_research_report") and not demo_safe:
        with st.expander("Last Reality-First Research Report", expanded=False):
            st.json(st.session_state.last_reality_research_report)


def search_sources_caption() -> str:
    """One line describing the web search sources, in the order they are tried."""

    parts = []
    for source in search_sources_status():
        if not source["available"]:
            state = f"off ({source['setup']})"
        elif source["cooldown_seconds"]:
            state = f"skipped for {source['cooldown_seconds']}s after an error"
        else:
            state = "on"
        parts.append(f"{source['label']}: {state}")
    return "Search sources, tried in order and switched automatically: " + " → ".join(parts)


def render_web_research_tab(settings: dict[str, Any]) -> None:
    st.subheader("Web Research")
    st.caption(search_sources_caption())
    demo_safe = is_demo_safe(settings)
    query = st.text_input("Search query", placeholder="What should Cognitive Nexus research?")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        max_results = st.slider("Results", 1, 10, 5)
    with col2:
        scrape_pages = st.checkbox("Scrape pages", value=True)
    with col3:
        summarize = st.checkbox("Summarize with AI", value=True)
    with col4:
        save_locally = st.checkbox("Save locally", value=True)
    save_to_memory = st.checkbox("Add cleaned research to local knowledge memory", value=True)

    if st.button("Run Web Research", type="primary"):
        if not query.strip():
            st.warning("Enter a search query first.")
            return
        with st.status("Researching...", expanded=True) as status:
            try:
                research = get_nexus_core().run_web_research(
                    query,
                    max_results=max_results,
                    scrape_pages=scrape_pages,
                    summarize_with_ai=summarize,
                    save_locally=save_locally,
                    save_to_memory=save_to_memory,
                    settings=settings,
                )
            except ContentRuleBlocked as stopped:
                status.update(label="Not run", state="error")
                st.warning(stopped.reply)
                return
            status.update(label="Research complete", state="complete")
        if research["errors"]:
            st.warning("\n".join(research["errors"]))
        st.markdown("### Summary")
        st.markdown(research["summary"])
        research_label = "" if demo_safe else describe_answer(research.get("produced_by"))
        if research_label:
            st.caption(research_label)
        if research.get("saved_paths"):
            if demo_safe:
                st.success("Research saved locally. File paths hidden in Demo Safe Mode.")
            else:
                st.success(f"Saved JSON: {research['saved_paths'].get('json')}")
                st.success(f"Saved Markdown: {research['saved_paths'].get('markdown')}")
        st.markdown("### Sources")
        for result in research["results"]:
            st.markdown(f"**[{result.get('title') or result.get('url')}]({result.get('url')})**")
            st.caption(result.get("source", ""))
            st.write(result.get("snippet", ""))
        with st.expander("Scraped page previews", expanded=False):
            for page in research["scraped_pages"]:
                st.markdown(f"**[{page.get('title') or page.get('url')}]({page.get('url')})**")
                if page.get("success"):
                    st.write(page.get("excerpt", ""))
                else:
                    st.warning(page.get("error", "Scrape failed."))
