# -*- coding: utf-8 -*-
"""
InsaatAudit — NiceGUI + Apache ECharts + Cytoscape.js Görsel Denetim Stüdyosu
===============================================================================
Çalıştırma:
  .\venv\Scripts\python.exe -X utf8 ui_app.py
"""

from __future__ import annotations

import json
import queue
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from nicegui import app, run, ui

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.project_db import VALID_STATES  # noqa: E402
from utils.ui_service import (  # noqa: E402
    NODE_LABELS,
    build_docx_bytes_from_markdown,
    get_correspondence_graph,
    get_document_chunks,
    get_legislation_sync_status,
    get_memory_inventory_and_tree,
    list_known_projects,
    list_sample_petitions,
    run_audit_streaming,
    run_legislation_check,
    run_legislation_sync,
    save_uploaded_petition,
    semantic_search_memory,
    update_card_and_approve,
)

# ==============================================================================
# Stil & İstemci Kütüphaneleri (Daylight Engineering Workbench)
# ==============================================================================
HEAD_HTML = """
<script src="https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background-color: #F5F7FA;
    color: #1E293B;
  }
  .surface-panel {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
  }
  .metric-val {
    font-variant-numeric: tabular-nums;
    color: #102C57;
    font-weight: 700;
    font-size: 1.5rem;
    line-height: 1.2;
  }
  .mono-code {
    font-family: 'JetBrains Mono', Consolas, monospace;
  }
  .report-markdown table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    margin: 10px 0;
    font-size: 0.84rem;
  }
  .report-markdown th, .report-markdown td {
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .report-markdown th {
    background: #102C57;
    color: #FFFFFF;
    text-align: left;
    padding: 7px 9px;
    border: 1px solid #CBD5E1;
  }
  .report-markdown td {
    padding: 6px 9px;
    border: 1px solid #E2E8F0;
    vertical-align: top;
  }
  .report-markdown tr:nth-child(even) td {
    background: #F8FAFC;
  }
  .report-markdown h1 {
    color: #102C57;
    font-size: 1.15rem;
    line-height: 1.3;
    margin-top: 1.0rem;
    margin-bottom: 0.4rem;
    font-weight: 700;
  }
  .report-markdown h2 {
    color: #102C57;
    font-size: 1.02rem;
    line-height: 1.3;
    margin-top: 0.9rem;
    margin-bottom: 0.35rem;
    font-weight: 700;
  }
  .report-markdown h3 {
    color: #0F766E;
    font-size: 0.95rem;
    margin-top: 0.75rem;
    margin-bottom: 0.3rem;
    font-weight: 600;
  }
</style>
<script>
window.renderCorrespondenceGraph = function(containerId, elementsJson) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (typeof cytoscape === 'undefined') {
    el.innerHTML = '<div style="padding:20px;color:#BA181B;">Cytoscape.js CDN yüklenemedi (internet bağlantısı gerekir).</div>';
    return;
  }
  const elements = typeof elementsJson === 'string' ? JSON.parse(elementsJson) : elementsJson;
  if (window._cyInstance) {
    window._cyInstance.destroy();
    window._cyInstance = null;
  }
  if (!elements || elements.length === 0) {
    el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:24px;text-align:center;color:#64748B;font-size:0.9rem;"><div><div style="font-weight:600;color:#102C57;margin-bottom:6px;">Yazışma Havuzu Şu An Boş (0 Kayıt)</div><div>Seçili proje için henüz yüklenici / idare yazışması indekslenmedi.<br/>Gerçek yazışmalar eklendiğinde <code>ingest_history.py --project &lt;proje&gt;</code> ile soy ağacı otomatik çizilir.</div></div></div>';
    return;
  }
  el.innerHTML = '';
  window._cyInstance = cytoscape({
    container: el,
    elements: elements,
    layout: {
      name: 'breadthfirst',
      directed: true,
      padding: 24,
      spacingFactor: 1.35,
      avoidOverlap: true
    },
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'text-wrap': 'wrap',
          'text-max-width': '160px',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '11px',
          'font-family': 'Inter, sans-serif',
          'color': '#0F172A',
          'background-color': '#EFF6FF',
          'border-width': 1.5,
          'border-color': '#1D4ED8',
          'shape': 'round-rectangle',
          'width': '168px',
          'height': '64px',
          'padding': '6px'
        }
      },
      {
        selector: 'node[node_kind = "administration"]',
        style: {
          'background-color': '#ECFDF5',
          'border-color': '#0F766E'
        }
      },
      {
        selector: 'node[node_kind = "consultant"]',
        style: {
          'background-color': '#FFFBEB',
          'border-color': '#B45309'
        }
      },
      {
        selector: 'node[node_kind = "pending"]',
        style: {
          'background-color': '#FEF2F2',
          'border-color': '#BA181B',
          'border-style': 'dashed',
          'border-width': 2
        }
      },
      {
        selector: 'node[node_kind = "unresolved"]',
        style: {
          'background-color': '#F1F5F9',
          'border-color': '#64748B',
          'border-style': 'dotted',
          'color': '#475569'
        }
      },
      {
        selector: 'node:selected',
        style: {
          'border-width': 3,
          'border-color': '#102C57',
          'background-color': '#DBEAFE'
        }
      },
      {
        selector: 'edge',
        style: {
          'label': 'data(label)',
          'font-size': '10px',
          'color': '#475569',
          'text-background-color': '#FFFFFF',
          'text-background-opacity': 0.85,
          'text-background-padding': '2px',
          'width': 1.8,
          'line-color': '#64748B',
          'target-arrow-color': '#64748B',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier'
        }
      },
      {
        selector: 'edge[!resolved]',
        style: {
          'line-style': 'dashed',
          'line-color': '#CBD5E1',
          'target-arrow-color': '#CBD5E1'
        }
      }
    ]
  });
  window._cyInstance.resize();
  window._cyInstance.fit(undefined, 24);
  window._cyInstance.on('tap', 'node', function(evt) {
    emitEvent('cy_node_click', evt.target.data());
  });
};
</script>
"""


@ui.page("/")
def main_page() -> None:
    ui.add_head_html(HEAD_HTML)
    ui.colors(primary="#102C57", secondary="#0F766E", accent="#BA181B", positive="#15803D")

    known_projects = list_known_projects()
    initial_inv = get_memory_inventory_and_tree()

    # Üst Çubuk
    with ui.header().classes("bg-[#102C57] text-white px-6 py-3 items-center justify-between border-b border-slate-800"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("account_balance", size="28px").classes("text-teal-300")
            with ui.column().classes("gap-0"):
                ui.label("InsaatAudit — Mevzuat, Şartname ve Yazışma Denetim Stüdyosu").classes("text-lg font-bold tracking-tight")
                ui.label("Katmanlı Vektör Hafıza · SQLite Yazışma Soy Ağacı · 6 Düğümlü LangGraph Denetimi").classes("text-xs text-slate-300")
        header_badge = ui.badge(
            f"Normatif DB: {initial_inv['normative_vectors']:,} · Yazışma DB: {initial_inv['correspondence_vectors']:,}",
            color="teal",
        ).classes("text-xs px-3 py-1")

    with ui.column().classes("w-full max-w-[1440px] mx-auto px-5 py-4 gap-4"):
        with ui.tabs().classes("w-full bg-white border border-slate-200 rounded-lg px-2 text-slate-700") as tabs:
            tab_mem = ui.tab("Hafıza & Bilgi Ağacı", icon="account_tree")
            tab_corr = ui.tab("Yazışma Soy Ağacı & Onay", icon="hub")
            tab_audit = ui.tab("Dilekçe Yükle & Canlı Denetle", icon="fact_check")
            tab_sync = ui.tab("Mevzuat Güncelleme Merkezi", icon="sync")

        with ui.tab_panels(tabs, value=tab_mem).props("animated=false").classes("w-full bg-transparent p-0"):
            # ==================================================================
            # SEKME 1: HAFIZA & BİLGİ AĞACI (Apache ECharts + Arama)
            # ==================================================================
            with ui.tab_panel(tab_mem).classes("p-0 gap-4"):
                inv_state: Dict[str, Any] = {"data": initial_inv}
                top_subs_init = list(initial_inv["subsystem_counts"].items())[:12]
                top_subs_init.reverse()

                with ui.row().classes("w-full gap-3"):
                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[180px]"):
                        ui.label("Normatif DB (vector_db)").classes("text-xs font-medium text-slate-500")
                        lbl_tot = ui.label(f"{initial_inv['normative_vectors']:,}").classes("metric-val")
                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[180px]"):
                        ui.label("Katman 1 — Genel Mevzuat & Norm").classes("text-xs font-medium text-slate-500")
                        lbl_l1 = ui.label(f"{initial_inv['layer_counts'].get('global', 0):,}").classes("metric-val")
                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[180px]"):
                        ui.label("Katman 2 — Proje Sözleşme/Şartname").classes("text-xs font-medium text-slate-500")
                        lbl_l2 = ui.label(f"{initial_inv['layer_counts'].get('project_normative', 0):,}").classes("metric-val")
                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[180px]"):
                        ui.label("Katman 3 — Ayrı Yazışma DB (vector_db_yazismalar)").classes("text-xs font-medium text-slate-500")
                        lbl_l3 = ui.label(f"{initial_inv['correspondence_vectors']:,}").classes("metric-val")

                with ui.row().classes("w-full gap-4 items-stretch"):
                    with ui.column().classes("surface-panel p-4 flex-[1.35] min-w-0 gap-2"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Katmanlı Bilgi Ağacı (ECharts — Yaprak Belgeye Tıklayın)").classes("text-base font-semibold text-[#102C57]")
                            ui.button("Hafızayı Yenile", icon="refresh", on_click=lambda: refresh_memory_tab()).props("flat dense color=primary")

                        tree_chart = ui.echart({
                            "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
                            "series": [{
                                "type": "tree",
                                "data": [initial_inv["tree"]],
                                "top": "4%",
                                "left": "25%",
                                "bottom": "4%",
                                "right": "28%",
                                "symbolSize": 9,
                                "initialTreeDepth": 2,
                                "expandAndCollapse": True,
                                "roam": True,
                                "label": {
                                    "position": "top",
                                    "verticalAlign": "bottom",
                                    "align": "center",
                                    "distance": 6,
                                    "fontSize": 10.5,
                                    "color": "#1E293B",
                                    "width": 165,
                                    "overflow": "truncate",
                                    "backgroundColor": "rgba(255,255,255,0.92)",
                                    "padding": [1, 4],
                                },
                                "leaves": {"label": {"position": "right", "verticalAlign": "middle", "align": "left", "fontSize": 10.5}},
                                "itemStyle": {"color": "#102C57", "borderColor": "#0F766E"},
                                "lineStyle": {"color": "#CBD5E1", "width": 1.4, "curveness": 0.45},
                            }],
                        }).classes("w-full h-[560px]")

                    with ui.column().classes("surface-panel p-4 flex-1 min-w-0 gap-2"):
                        chunk_header = ui.label("Belge İçerik İnceleyici").classes("text-base font-semibold text-[#102C57]")
                        chunk_sub = ui.label("Ağaçtan bir kanun, şartname veya yazışma yaprağına tıklayın.").classes("text-xs text-slate-500")
                        chunk_scroll = ui.scroll_area().classes("w-full h-[510px] border border-slate-100 rounded bg-slate-50 p-3")

                with ui.row().classes("w-full gap-4 items-stretch"):
                    with ui.column().classes("surface-panel p-4 flex-1 min-w-0 gap-2"):
                        ui.label("Disiplin Bazlı Vektör Dağılımı").classes("text-base font-semibold text-[#102C57]")
                        sub_chart = ui.echart({
                            "tooltip": {"trigger": "axis"},
                            "grid": {"left": "36%", "right": "6%", "top": "6%", "bottom": "8%"},
                            "xAxis": {"type": "value"},
                            "yAxis": {"type": "category", "data": [k for k, _ in top_subs_init], "axisLabel": {"fontSize": 11}},
                            "series": [{"type": "bar", "data": [v for _, v in top_subs_init], "itemStyle": {"color": "#0F766E", "borderRadius": [0, 4, 4, 0]}}],
                        }).classes("w-full h-[300px]")

                    with ui.column().classes("surface-panel p-4 flex-[1.2] min-w-[460px] gap-2"):
                        ui.label("Canlı Hibrit Hafıza Sorgusu (BM25 + BGE-M3 + Reranker)").classes("text-base font-semibold text-[#102C57]")
                        with ui.row().classes("w-full items-center gap-2"):
                            q_input = ui.input("Sorgu (ör. YİGŞ Madde 29 gecikme cezası veya 2013/5217 Pn formülü)").classes("flex-1").props("outlined dense")
                            q_store = ui.select(
                                {"normative_rule": "Normatif DB", "correspondence_history": "Yazışma DB"},
                                value="normative_rule",
                                label="Veritabanı",
                            ).props("outlined dense").classes("w-36")
                            q_proj = ui.select(["global"] + known_projects, value="ikitelli_atakoy_metro" if "ikitelli_atakoy_metro" in known_projects else "global", label="Kapsam").props("outlined dense").classes("w-44")
                            q_btn = ui.button("Ara", icon="search").props("unelevated color=primary")
                        search_results_box = ui.scroll_area().classes("w-full h-[240px] border border-slate-100 rounded bg-slate-50 p-3")

                def on_tree_click(e) -> None:
                    data_dict = e.data or {}
                    meta = data_dict.get("meta")
                    if not meta:
                        return
                    sf = meta["source_file"]
                    pid = meta["project_id"]
                    drole = meta.get("doc_role") or ("correspondence_history" if meta.get("layer") == "Katman 3" else "normative_rule")
                    chunk_header.text = sf
                    chunk_sub.text = f"{meta.get('layer', '')} · Proje: {pid} · Tür: {meta.get('doc_type', '')}"
                    chunks = get_document_chunks(pid, sf, limit=60, doc_role=drole)
                    chunk_scroll.clear()
                    with chunk_scroll:
                        if not chunks:
                            ui.label("Bu dosya için parça bulunamadı.").classes("text-sm text-slate-500")
                            return
                        for idx, ch in enumerate(chunks, 1):
                            m = ch["metadata"]
                            pg = f"Sayfa {m.get('page_num')}" if m.get("page_num", 0) > 0 else "Dijital"
                            stds = m.get("standard_codes") or "-"
                            with ui.column().classes("w-full bg-white border border-slate-200 rounded p-3 mb-2 gap-1"):
                                with ui.row().classes("w-full justify-between items-center"):
                                    ui.label(f"#{idx} · {m.get('title', 'Başlık yok')[:72]}").classes("text-xs font-semibold text-[#102C57]")
                                    ui.badge(f"{pg} | {m.get('subsystem', '')}", color="teal").props("outline").classes("text-[10px]")
                                if stds != "-":
                                    ui.label(f"Standartlar: {stds}").classes("text-[11px] mono-code text-teal-700")
                                ui.label(ch["content"][:900] + ("..." if len(ch["content"]) > 900 else "")).classes("text-xs text-slate-700 whitespace-pre-wrap")

                tree_chart.on_point_click(on_tree_click)

                async def run_live_search() -> None:
                    q_txt = (q_input.value or "").strip()
                    if not q_txt:
                        ui.notify("Lütfen arama ifadesi girin.", type="warning")
                        return
                    q_btn.disable()
                    search_results_box.clear()
                    with search_results_box:
                        ui.spinner(size="md")
                        ui.label("BGE-M3 + BM25 + Reranker çalışıyor...").classes("text-xs text-slate-500")
                    try:
                        hits = await run.io_bound(semantic_search_memory, q_txt, q_proj.value, None, q_store.value, 5)
                    finally:
                        q_btn.enable()
                    search_results_box.clear()
                    with search_results_box:
                        if not hits:
                            ui.label("Eşleşen sonuç bulunamadı.").classes("text-sm text-slate-500")
                            return
                        for h in hits:
                            m = h["metadata"]
                            pg = f"Sayfa {m.get('page_num')}" if m.get("page_num", 0) > 0 else "Dijital"
                            with ui.column().classes("w-full bg-white border border-slate-200 rounded p-2.5 mb-2 gap-1"):
                                ui.label(f"{m.get('source_file', '?')} ({pg}) — Skor: {h.get('rerank_score', 0.0):.3f}").classes("text-xs font-semibold text-[#102C57]")
                                ui.label(f"Başlık: {m.get('title', '')[:80]} | Disiplin: {m.get('subsystem', '')}").classes("text-[11px] text-teal-700")
                                ui.label(h["content"][:480] + ("..." if len(h["content"]) > 480 else "")).classes("text-xs text-slate-700 whitespace-pre-wrap")

                q_btn.on_click(run_live_search)
                q_input.on("keydown.enter", run_live_search)

                def refresh_memory_tab() -> None:
                    inv = get_memory_inventory_and_tree()
                    inv_state["data"] = inv
                    lbl_tot.text = f"{inv['normative_vectors']:,}"
                    lbl_l1.text = f"{inv['layer_counts'].get('global', 0):,}"
                    lbl_l2.text = f"{inv['layer_counts'].get('project_normative', 0):,}"
                    lbl_l3.text = f"{inv['correspondence_vectors']:,}"
                    header_badge.text = f"Normatif DB: {inv['normative_vectors']:,} · Yazışma DB: {inv['correspondence_vectors']:,}"
                    tree_chart.options["series"][0]["data"] = [inv["tree"]]
                    tree_chart.update()
                    top_subs = list(inv["subsystem_counts"].items())[:12]
                    top_subs.reverse()
                    sub_chart.options["yAxis"]["data"] = [k for k, _ in top_subs]
                    sub_chart.options["series"][0]["data"] = [v for _, v in top_subs]
                    sub_chart.update()

            # ==================================================================
            # SEKME 2: YAZIŞMA SOY AĞACI & ONAY KUYRUĞU (Cytoscape + SQLite)
            # ==================================================================
            with ui.tab_panel(tab_corr).classes("p-0 gap-4"):
                corr_state: Dict[str, Any] = {"selected_doc_id": None}

                with ui.row().classes("surface-panel w-full p-3 items-center justify-between gap-3"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Proje Yazışma Çizgesi (project_graph.db)").classes("text-base font-semibold text-[#102C57]")
                        corr_proj_select = ui.select(["Tümü"] + known_projects, value="Tümü", label="Proje Filtresi").props("outlined dense").classes("w-56")
                    with ui.row().classes("items-center gap-2"):
                        ui.badge("Yüklenici", color="blue").props("outline")
                        ui.badge("İdare", color="teal").props("outline")
                        ui.badge("Müşavir", color="amber").props("outline")
                        ui.badge("İnsan Onayı Bekliyor", color="red").props("outline")
                        ui.button("Çizgeyi Yenile", icon="refresh", on_click=lambda: refresh_corr_tab()).props("flat dense color=primary")

                with ui.row().classes("w-full gap-4 items-stretch"):
                    with ui.column().classes("surface-panel p-3 flex-[1.4] min-w-[520px]"):
                        ui.html('<div id="cy_correspondence" style="width:100%;height:460px;background:#FAFBFC;border:1px solid #E2E8F0;border-radius:6px;"></div>').classes("w-full")

                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[380px] gap-2"):
                        ui.label("Seçili Evrak Kartı & İnsan Onayı").classes("text-base font-semibold text-[#102C57]")
                        sel_doc_info = ui.label("Grafikteki bir kutuya veya aşağıdaki onay kuyruğuna tıklayın.").classes("text-xs text-slate-500")
                        ed_no = ui.input("Evrak Sayısı (doc_no)").props("outlined dense").classes("w-full")
                        ed_date = ui.input("Tarih (YYYY-MM-DD)").props("outlined dense").classes("w-full")
                        ed_subj = ui.input("Konu").props("outlined dense").classes("w-full")
                        ed_state = ui.select(list(VALID_STATES), value="Acik", label="Talep Durumu (confirmed_by_human=1)").props("outlined dense").classes("w-full")
                        ed_meta_lbl = ui.label("").classes("text-xs text-slate-600 whitespace-pre-wrap")
                        ed_summary_box = ui.label("").classes("text-xs bg-slate-50 border border-slate-200 rounded p-2 w-full max-h-28 overflow-auto")
                        btn_approve = ui.button("Değişiklikleri Kaydet & İnsan Onayı Ver", icon="verified").props("unelevated color=primary").classes("w-full")

                with ui.row().classes("w-full gap-4 items-stretch"):
                    with ui.column().classes("surface-panel p-4 flex-1 gap-2"):
                        pend_title = ui.label("İnsan Onayı Bekleyenler (pending_review)").classes("text-sm font-semibold text-[#BA181B]")
                        pend_table = ui.table(
                            columns=[
                                {"name": "doc_no", "label": "Sayı", "field": "doc_no", "align": "left"},
                                {"name": "doc_date", "label": "Tarih", "field": "doc_date", "align": "left"},
                                {"name": "sender_role", "label": "Taraf", "field": "sender_role", "align": "left"},
                                {"name": "state", "label": "Durum", "field": "state", "align": "left"},
                                {"name": "subject", "label": "Konu", "field": "subject", "align": "left"},
                            ],
                            rows=[],
                            row_key="doc_id",
                            selection="single",
                            pagination=5,
                        ).classes("w-full")

                    with ui.column().classes("surface-panel p-4 flex-1 gap-2"):
                        ui.label("Durum Geçişi Denetim İzi (state_history)").classes("text-sm font-semibold text-[#102C57]")
                        hist_table = ui.table(
                            columns=[
                                {"name": "doc_id", "label": "Belge ID", "field": "doc_id", "align": "left"},
                                {"name": "old_state", "label": "Önceki", "field": "old_state", "align": "left"},
                                {"name": "new_state", "label": "Yeni", "field": "new_state", "align": "left"},
                                {"name": "confirmed_by_human", "label": "Onay", "field": "confirmed_by_human", "align": "center"},
                                {"name": "changed_at", "label": "Zaman", "field": "changed_at", "align": "left"},
                            ],
                            rows=[],
                            row_key="history_id",
                            pagination=5,
                        ).classes("w-full")

                def load_card_into_editor(card: Dict[str, Any]) -> None:
                    did = card.get("doc_id") or card.get("id")
                    if not did or str(did).startswith("unresolved::"):
                        sel_doc_info.text = f"Çözülmemiş Referans: {card.get('doc_no', '')} — Henüz veritabanında yok."
                        corr_state["selected_doc_id"] = None
                        return
                    corr_state["selected_doc_id"] = did
                    sel_doc_info.text = f"Seçili Kayıt: {did} ({card.get('review_status', '')})"
                    ed_no.value = card.get("doc_no") or ""
                    ed_date.value = card.get("doc_date") or ""
                    ed_subj.value = card.get("subject") or ""
                    if card.get("state") in VALID_STATES:
                        ed_state.value = card.get("state")
                    ed_meta_lbl.text = (
                        f"Kanıt Ağırlığı: {card.get('evidence_weight', '-')} | İlgi: {card.get('ilgi_raw', '-')}\n"
                        f"Etiketler: {card.get('tags', '-')}"
                    )
                    ed_summary_box.text = card.get("summary") or "(Özet metni yok)"

                ui.on("cy_node_click", lambda e: load_card_into_editor(e.args or {}))
                pend_table.on_select(lambda e: load_card_into_editor(e.selection[0]) if e.selection else None)
                pend_table.on("rowClick", lambda e: load_card_into_editor(e.args[1]) if (e.args and len(e.args) > 1 and isinstance(e.args[1], dict)) else None)

                async def save_approval_click() -> None:
                    did = corr_state.get("selected_doc_id")
                    if not did:
                        ui.notify("Önce grafikten veya tablodan bir belge seçin.", type="warning")
                        return
                    try:
                        res = update_card_and_approve(
                            doc_id=did,
                            doc_date=ed_date.value,
                            doc_no=ed_no.value,
                            subject=ed_subj.value,
                            new_state=ed_state.value,
                            confirmed_by_human=True,
                        )
                        msg = "Kart insan onayıyla kaydedildi"
                        if res["state_changed"]:
                            msg += f" ve durum '{ed_state.value}' olarak güncellendi."
                        ui.notify(msg, type="positive")
                        await refresh_corr_tab()
                    except Exception as exc:
                        ui.notify(f"Hata: {exc}", type="negative")

                btn_approve.on_click(save_approval_click)

                async def refresh_corr_tab() -> None:
                    sel_p = corr_proj_select.value
                    g = get_correspondence_graph(project_id=None if sel_p == "Tümü" else sel_p)
                    pend_table.rows = g["pending_review"]
                    pend_table.update()
                    pend_title.text = f"İnsan Onayı Bekleyenler ({len(g['pending_review'])})"
                    hist_table.rows = g["state_history"]
                    hist_table.update()
                    elem_json = json.dumps(g["elements"], ensure_ascii=False)
                    await ui.run_javascript(f"window.renderCorrespondenceGraph('cy_correspondence', {elem_json});")

                corr_proj_select.on_value_change(lambda _: refresh_corr_tab())

            # ==================================================================
            # SEKME 3: DİLEKÇE YÜKLE & CANLI DENETLE (2_agents_graph.py)
            # ==================================================================
            with ui.tab_panel(tab_audit).classes("p-0 gap-4"):
                audit_state: Dict[str, Any] = {
                    "target_path": None,
                    "report_md": "",
                    "report_title": "Denetim Raporu",
                    "running": False,
                    "q": queue.Queue(),
                    "step_rows": {},
                }

                with ui.row().classes("w-full gap-4 items-stretch"):
                    with ui.column().classes("surface-panel p-4 w-[410px] gap-3"):
                        ui.label("1. Evrak Seç veya Yükle").classes("text-base font-semibold text-[#102C57]")
                        audit_proj = ui.select(
                            ["Otomatik / Klasörden"] + known_projects,
                            value="ikitelli_atakoy_metro" if "ikitelli_atakoy_metro" in known_projects else "Otomatik / Klasörden",
                            label="Hedef Proje Kapsamı",
                        ).props("outlined dense").classes("w-full")

                        samples = list_sample_petitions()
                        sample_map = {s["label"]: s["path"] for s in samples}
                        sample_sel = ui.select(
                            options=list(sample_map.keys()),
                            value=list(sample_map.keys())[0] if sample_map else None,
                            label="Hazır / İndirilen Evrak Seç",
                        ).props("outlined dense").classes("w-full")

                        def use_sample_click() -> None:
                            if sample_sel.value and sample_sel.value in sample_map:
                                audit_state["target_path"] = Path(sample_map[sample_sel.value])
                                lbl_chosen.text = f"Seçili Dosya: {audit_state['target_path'].name}"
                                ui.notify(f"Hazır evrak seçildi: {audit_state['target_path'].name}", type="info")

                        ui.button("Seçili Evrağı Kullan", icon="description", on_click=use_sample_click).props("outline color=primary dense").classes("w-full")

                        async def handle_upload(e) -> None:
                            raw_bytes = await e.file.read()
                            proj_for_save = audit_proj.value if audit_proj.value != "Otomatik / Klasörden" else "ornek_proje"
                            saved = save_uploaded_petition(e.file.name, raw_bytes, proj_for_save)
                            audit_state["target_path"] = saved
                            lbl_chosen.text = f"Yüklendi: {saved.name} ({len(raw_bytes):,} B)"
                            ui.notify(f"Evrak kaydedildi: {saved.name}", type="positive")

                        ui.upload(
                            label="Veya PDF / DOCX / MD / TXT Yükle",
                            auto_upload=True,
                            on_upload=handle_upload,
                        ).classes("w-full").props("flat bordered accept='.pdf,.docx,.md,.txt,.html'")

                        lbl_chosen = ui.label("Henüz dosya seçilmedi.").classes("text-xs font-medium text-teal-700 break-all")
                        btn_start_audit = ui.button("6 Ajanlı Denetimi Başlat", icon="play_arrow").props("unelevated color=primary").classes("w-full")

                        ui.separator()
                        ui.label("2. Canlı LangGraph Akış Adımları").classes("text-sm font-semibold text-[#102C57]")
                        step_box = ui.column().classes("w-full gap-1.5")
                        with step_box:
                            for node_key, node_title in NODE_LABELS.items():
                                with ui.row().classes("w-full items-center justify-between bg-slate-50 border border-slate-200 rounded px-2.5 py-1.5"):
                                    lbl_st = ui.label(f"○ {node_title}").classes("text-xs font-medium text-slate-600")
                                    lbl_det = ui.label("Bekliyor").classes("text-[11px] text-slate-400")
                                    audit_state["step_rows"][node_key] = (lbl_st, lbl_det, node_title)

                    with ui.column().classes("surface-panel p-4 flex-1 min-w-[540px] gap-3"):
                        with ui.row().classes("w-full items-center justify-between"):
                            report_header = ui.label("Nihai Denetim Raporu").classes("text-base font-semibold text-[#102C57]")
                            with ui.row().classes("gap-2"):
                                btn_dl_docx = ui.button("Word (.docx) İndir", icon="download").props("unelevated color=secondary dense")
                                btn_dl_md = ui.button("Markdown (.md) İndir", icon="article").props("outline color=primary dense")
                                btn_dl_docx.disable()
                                btn_dl_md.disable()

                        report_scroll = ui.scroll_area().classes("w-full h-[610px] border border-slate-100 rounded bg-white p-4")
                        with report_scroll:
                            report_md_view = ui.markdown("Sol panelden bir yüklenici dilekçesi veya SAT raporu seçip **6 Ajanlı Denetimi Başlat**'a tıklayın.").classes("report-markdown w-full")

                def download_docx() -> None:
                    if not audit_state["report_md"]:
                        return
                    docx_bytes = build_docx_bytes_from_markdown(audit_state["report_md"], audit_state["report_title"])
                    fname = f"Denetim_Raporu_{Path(audit_state['target_path']).stem if audit_state['target_path'] else 'Rapor'}.docx"
                    ui.download(docx_bytes, filename=fname)

                def download_md() -> None:
                    if not audit_state["report_md"]:
                        return
                    fname = f"Denetim_Raporu_{Path(audit_state['target_path']).stem if audit_state['target_path'] else 'Rapor'}.md"
                    ui.download(audit_state["report_md"].encode("utf-8"), filename=fname)

                btn_dl_docx.on_click(download_docx)
                btn_dl_md.on_click(download_md)

                def poll_audit_queue() -> None:
                    q: queue.Queue = audit_state["q"]
                    while not q.empty():
                        ev_type, payload = q.get_nowait()
                        if ev_type == "node":
                            nk, summary = payload
                            if nk in audit_state["step_rows"]:
                                lst, ldet, ntitle = audit_state["step_rows"][nk]
                                lst.text = f"✔ {ntitle}"
                                lst.classes(replace="text-xs font-semibold text-[#0F766E]")
                                ldet.text = summary[:85]
                                ldet.classes(replace="text-[11px] text-slate-600")
                        elif ev_type == "done":
                            audit_timer.active = False
                            audit_state["running"] = False
                            btn_start_audit.enable()
                            final_md = payload.get("final_report", "")
                            audit_state["report_md"] = final_md
                            report_md_view.content = final_md or "(Boş rapor)"
                            report_header.text = f"Nihai Rapor Hazır — {Path(payload.get('saved_report_path', '')).name}"
                            btn_dl_docx.enable()
                            btn_dl_md.enable()
                            ui.notify("6 aşamalı denetim raporu tamamlandı!", type="positive")
                        elif ev_type == "error":
                            audit_timer.active = False
                            audit_state["running"] = False
                            btn_start_audit.enable()
                            ui.notify(f"Denetim hatası: {payload}", type="negative")
                            report_md_view.content = f"**Hata:** `{payload}`"

                audit_timer = ui.timer(0.35, poll_audit_queue, active=False)

                async def start_live_audit() -> None:
                    if audit_state["running"]:
                        return
                    if not audit_state["target_path"] and sample_sel.value in sample_map:
                        audit_state["target_path"] = Path(sample_map[sample_sel.value])
                        lbl_chosen.text = f"Seçili Dosya: {audit_state['target_path'].name}"
                    if not audit_state["target_path"] or not Path(audit_state["target_path"]).exists():
                        ui.notify("Önce geçerli bir evrak seçin veya yükleyin.", type="warning")
                        return

                    audit_state["running"] = True
                    btn_start_audit.disable()
                    btn_dl_docx.disable()
                    btn_dl_md.disable()
                    audit_state["report_md"] = ""
                    audit_state["report_title"] = f"Denetim Raporu: {Path(audit_state['target_path']).name}"
                    report_md_view.content = "Denetim çalışıyor... PDF ise önce Docling/RapidOCR ile metne çevrilir, ardından 6 ajan düğümü sırayla yürütülür."
                    for nk, (lst, ldet, ntitle) in audit_state["step_rows"].items():
                        lst.text = f"○ {ntitle}"
                        lst.classes(replace="text-xs font-medium text-slate-600")
                        ldet.text = "Çalışıyor / Sırada..."
                        ldet.classes(replace="text-[11px] text-slate-400")

                    q: queue.Queue = audit_state["q"]
                    while not q.empty():
                        q.get_nowait()
                    audit_timer.active = True

                    chosen_path = Path(audit_state["target_path"])
                    chosen_proj = audit_proj.value

                    def _worker() -> None:
                        try:
                            res = run_audit_streaming(
                                chosen_path,
                                project_id=chosen_proj,
                                progress_cb=lambda nk, summ, _: q.put(("node", (nk, summ))),
                            )
                            q.put(("done", res))
                        except Exception as exc:
                            q.put(("error", str(exc)))

                    # Arka plan iş parçacığında koş; polling timer UI'yi ana döngüde günceller
                    import threading
                    threading.Thread(target=_worker, daemon=True).start()

                btn_start_audit.on_click(start_live_audit)

            # ==================================================================
            # SEKME 4: MEVZUAT GÜNCELLEME MERKEZİ (sync_mevzuat.py)
            # ==================================================================
            with ui.tab_panel(tab_sync).classes("p-0 gap-4"):
                with ui.row().classes("surface-panel w-full p-4 items-center justify-between"):
                    with ui.column().classes("gap-0.5"):
                        ui.label("Katman 1 Resmi Mevzuat Senkronizasyon & Sürüm Koruma Merkezi").classes("text-base font-semibold text-[#102C57]")
                        sync_meta_lbl = ui.label("Son senkronizasyon yükleniyor...").classes("text-xs text-slate-500")
                    with ui.row().classes("gap-2"):
                        btn_check_deep = ui.button("Canlı Kontrol (--check --deep)", icon="manage_search").props("outline color=primary")
                        btn_sync_ingest = ui.button("Değişenleri Eşitle & İndeksle", icon="sync").props("unelevated color=secondary")

                sync_status_lbl = ui.label("").classes("text-xs font-medium text-teal-700")

                with ui.column().classes("w-full gap-4"):
                    with ui.column().classes("surface-panel p-4 w-full min-w-0 gap-2"):
                        ui.label("Kayıtlı Resmi Mevzuat Kaynakları").classes("text-sm font-semibold text-[#102C57]")
                        sync_table = ui.table(
                            columns=[
                                {"name": "key", "label": "Anahtar", "field": "key", "align": "left"},
                                {"name": "title", "label": "Resmi Başlık", "field": "title", "align": "left", "style": "max-width: 420px; white-space: normal;"},
                                {"name": "version_tag", "label": "Sürüm / RG", "field": "version_tag", "align": "left"},
                                {"name": "char_count", "label": "Karakter", "field": "char_count", "align": "right"},
                                {"name": "last_checked_at", "label": "Son Kontrol", "field": "last_checked_at", "align": "left"},
                            ],
                            rows=[],
                            row_key="key",
                            pagination=10,
                        ).props("dense flat wrap-cells").classes("w-full")

                    with ui.column().classes("surface-panel p-4 w-full min-w-0 gap-2"):
                        ui.label("Son Değişiklik & Fark (Diff) Raporu").classes("text-sm font-semibold text-[#102C57]")
                        diff_scroll = ui.scroll_area().classes("w-full h-[380px] border border-slate-100 rounded bg-slate-50 p-3")
                        with diff_scroll:
                            diff_md_view = ui.markdown("").classes("report-markdown w-full text-xs")

                def refresh_sync_tab() -> None:
                    st = get_legislation_sync_status()
                    sync_meta_lbl.text = f"Kayıtlı Kaynak: {st['total_catalog']} | Son Güncelleme: {st['updated_at']}"
                    sync_table.rows = st["rows"]
                    sync_table.update()
                    diff_md_view.content = st["latest_report_text"] or "Henüz senkronizasyon raporu bulunmuyor."

                async def do_deep_check() -> None:
                    btn_check_deep.disable()
                    sync_status_lbl.text = "mevzuat.gov.tr ve ihale.gov.tr canlı kontrol ediliyor..."
                    try:
                        res = await run.io_bound(run_legislation_check, True)
                        updates = [i for i in res["items"] if i["status"] == "update_available"]
                        errs = [i for i in res["items"] if i["status"] == "error"]
                        sync_status_lbl.text = (
                            f"Kontrol tamamlandı ({res['checked_at']}): "
                            f"Güncelleme var={len(updates)}, Hata={len(errs)}, Toplam={len(res['items'])}"
                        )
                        ui.notify(sync_status_lbl.text, type="warning" if updates else "positive")
                    finally:
                        btn_check_deep.enable()

                async def do_sync_and_ingest() -> None:
                    btn_sync_ingest.disable()
                    sync_status_lbl.text = "Mevzuat güncelleniyor (eski sürümler _arsiv'e yedekleniyor) ve 1_ingest.py çalıştırılıyor..."
                    try:
                        res = await run.io_bound(run_legislation_sync, True)
                        upd = sum(1 for o in res.get("outcomes", []) if o.get("status") == "updated")
                        sync_status_lbl.text = f"Senkronizasyon tamamlandı: Güncellenen={upd} | Rapor: {Path(res.get('report_path', '')).name}"
                        ui.notify(sync_status_lbl.text, type="positive")
                        refresh_sync_tab()
                        refresh_memory_tab()
                    finally:
                        btn_sync_ingest.enable()

                btn_check_deep.on_click(do_deep_check)
                btn_sync_ingest.on_click(do_sync_and_ingest)

        # Sekme değişiminde ve ilk yüklemede tabloları ve grafikleri tazele
        async def on_tab_changed(e) -> None:
            if e.value == "Yazışma Soy Ağacı & Onay":
                await refresh_corr_tab()
            elif e.value == "Hafıza & Bilgi Ağacı":
                tree_chart.update()
                sub_chart.update()

        tabs.on_value_change(on_tab_changed)
        refresh_sync_tab()
        ui.timer(0.15, refresh_corr_tab, once=True)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="127.0.0.1",
        port=8080,
        title="InsaatAudit — Mevzuat & Şartname Denetim Stüdyosu",
        language="tr",
        reload=False,
        show=False,
    )
