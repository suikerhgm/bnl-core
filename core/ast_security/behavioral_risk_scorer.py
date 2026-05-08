"""
BehavioralRiskScorer — computes final risk level from a SemanticReport.

Scoring model:
    1. Base score = sum of all finding risk_scores (capped at 100)
    2. Any blacklisted finding → BLACKLISTED immediately
    3. Bonus risk for dangerous combinations (see COMBO_BONUSES)
    4. Bonus risk for high taint flow count
    5. Final level mapped from thresholds in dangerous_patterns.RISK_THRESHOLDS

Combination bonuses (stacked threats are more dangerous than their sum):
    obfuscation + exec chain      → +15
    network + credential strings  → +20
    persistence + subprocess      → +15
    privilege escalation + exec   → +25
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from core.ast_security.dangerous_patterns import RiskLevel, RISK_THRESHOLDS
from core.ast_security.semantic_analyzer import SemanticReport

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    """Final risk assessment computed from a SemanticReport."""
    scan_id:        str
    raw_score:      int
    final_score:    int
    risk_level:     str
    is_blacklisted: bool
    combo_bonuses:  int
    reasoning:      List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id":        self.scan_id,
            "raw_score":      self.raw_score,
            "final_score":    self.final_score,
            "risk_level":     self.risk_level,
            "is_blacklisted": self.is_blacklisted,
            "combo_bonuses":  self.combo_bonuses,
            "reasoning":      self.reasoning,
        }


class BehavioralRiskScorer:
    """Computes a final risk assessment from a SemanticReport."""

    def score(self, report: SemanticReport) -> RiskAssessment:
        reasoning: List[str] = []
        bonus = 0

        # Immediate blacklist: any blacklisted finding
        if report.has_blacklisted:
            for f in report.all_findings():
                p = getattr(f, "pattern", None)
                if p and p.blacklisted:
                    reasoning.append(f"BLACKLISTED: {p.name} ({p.id})")
            for flow in report.taint_flows:
                if flow.pattern.blacklisted:
                    reasoning.append(f"BLACKLISTED TAINT: {flow.pattern.name}")
            return RiskAssessment(
                scan_id=report.scan_id,
                raw_score=report.raw_risk_score,
                final_score=100,
                risk_level=RiskLevel.BLACKLISTED,
                is_blacklisted=True,
                combo_bonuses=0,
                reasoning=reasoning,
            )

        raw = report.raw_risk_score

        # Combination bonuses
        has_obf     = len(report.obfuscation) > 0
        has_exec    = any(f.pattern.id in ("CALL001","CALL002","CALL003")
                          for f in report.import_findings)
        has_net     = len([f for f in report.subprocess_abuse
                           if "network" in f.pattern.category]) > 0 or \
                     any("network" in str(f.pattern.category)
                         for f in report.exfiltration)
        has_persist = len(report.persistence) > 0
        has_sub     = len(report.subprocess_abuse) > 0
        has_priv    = len(report.privilege_esc) > 0
        has_exf     = len(report.exfiltration) > 0

        if has_obf and has_exec:
            bonus += 15; reasoning.append("combo: obfuscation+exec (+15)")
        if has_net and has_exf:
            bonus += 20; reasoning.append("combo: network+credential exfil (+20)")
        if has_persist and has_sub:
            bonus += 15; reasoning.append("combo: persistence+subprocess (+15)")
        if has_priv and has_sub:
            bonus += 25; reasoning.append("combo: privilege_esc+subprocess (+25)")

        # Taint flow bonus
        taint_bonus = min(20, len(report.taint_flows) * 5)
        if taint_bonus:
            bonus += taint_bonus
            reasoning.append(f"taint flows: {len(report.taint_flows)}×5 (+{taint_bonus})")

        # Syntax error with obfuscation — might be deliberate
        if report.has_syntax_error and has_obf:
            bonus += 10; reasoning.append("syntax_error+obfuscation (+10)")

        final = min(100, raw + bonus)

        # Map to level
        level = _score_to_level(final)

        # Top findings in reasoning
        top = sorted(report.all_findings(),
                     key=lambda f: getattr(f, "pattern", None) and f.pattern.risk_score or 0,
                     reverse=True)[:5]
        for f in top:
            p = getattr(f, "pattern", None)
            if p:
                reasoning.append(f"{p.category}/{p.id}: {p.name} (+{p.risk_score})")

        return RiskAssessment(
            scan_id=report.scan_id,
            raw_score=raw,
            final_score=final,
            risk_level=level,
            is_blacklisted=(level == RiskLevel.BLACKLISTED),
            combo_bonuses=bonus,
            reasoning=reasoning,
        )


def _score_to_level(score: int) -> str:
    if score <= 0:
        return RiskLevel.SAFE
    for level, (lo, hi) in RISK_THRESHOLDS.items():
        if level == RiskLevel.SAFE:
            continue
        if lo <= score <= hi:
            return level
    return RiskLevel.BLACKLISTED
