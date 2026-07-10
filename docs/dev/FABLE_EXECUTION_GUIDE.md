# Fable Execution Guide: LLM Council Complete Implementation

**Status:** Ready for Fable agent  
**Updated:** 2026-07-06  
**Duration:** ~4 hours  
**Token Strategy:** Minimize Sonnet sub-agents

---

## What Was Added to the Prompt

Your enhanced `FABLE_PROMPT.md` now includes:

### 1. **Gap Identification & Priority Matrix** ✅
   - How to audit the actual codebase
   - Real gaps likely to exist
   - Priority matrix (CRITICAL → HIGH → MEDIUM → LOW)
   - Gap-fix template for each issue

### 2. **Ease-of-Use Principles** ✅
   - 5 core questions to ask before shipping any code
   - Examples of bad vs. good error messages
   - Automation over manual setup philosophy

### 3. **Gap-Fix Strategy** ✅
   - Root cause analysis (not just symptoms)
   - Simplest-solution-first approach (not smartest)
   - Helpful error message requirements
   - Test + document each fix

### 4. **Critical First Step** ✅
   - Run the code before coding anything
   - Document actual gaps found
   - Create GAP REPORT with priorities

### 5. **Simplicity Rules (Non-Negotiable)** ✅
   - 7 red flags that mean "simplify this"
   - Examples of simplification patterns
   - Automation vs. configuration

### 6. **Real-World Testing** ✅
   - Fresh clone test
   - Error scenario test
   - New user test (watch them use it)
   - Docker test

### 7. **Ease-of-Use Scoring System** ✅
   - Quantifiable scoring for design decisions
   - When to simplify based on scores

### 8. **Final Checklists** ✅
   - CRITICAL fixes (must-do)
   - HIGH fixes (should-do)
   - MEDIUM fixes (nice-to-have)
   - LOW fixes (v2)

---

## Core Philosophy

**The prompt now emphasizes:**

| Principle | Why It Matters |
|-----------|----------------|
| **Simplicity > Features** | Users won't use what they don't understand |
| **Audit First** | Find real gaps, not imagined ones |
| **Fix Gaps, Don't Add Features** | Ship working v1, not perfect v2 |
| **Helpful Errors** | Make users self-sufficient |
| **Automate Setup** | Zero config > good docs |
| **Test Real Users** | Walk through it yourself |
| **Avoid Over-Engineering** | Boring code > clever code |

---

## Fable's Execution Path

**When Fable runs, it will:**

```
1. READ & AUDIT (30 min)
   └─ Run the code
   └─ Document actual gaps in GAP_REPORT
   └─ Prioritize by user impact

2. FIX CRITICAL GAPS (30-60 min)
   └─ App won't start? Fix it
   └─ Core functions broken? Fix it
   └─ Tests failing? Fix it
   
3. FIX HIGH-IMPACT GAPS (60-120 min)
   └─ Bad error messages → helpful ones
   └─ Missing setup scripts → add them
   └─ UI doesn't work → fix it
   
4. FIX MEDIUM GAPS (60-90 min)
   └─ Add start.sh / start.ps1
   └─ Add .env.example
   └─ Remove setup friction
   
5. ADD CORE DELIVERABLES (90 min)
   └─ Presets & demo personas
   └─ Metrics endpoint
   └─ Better streaming
   
6. TEST & POLISH (30 min)
   └─ Run quality checklist
   └─ Test error scenarios
   
7. DOCUMENTATION (40 min)
   └─ Complete FIRST_RUN.md
   └─ Complete API.md
   └─ Complete TROUBLESHOOTING.md
   
8. FINAL VALIDATION (20 min)
   └─ Fresh clone test
   └─ Docker test
   └─ Error scenario test

TOTAL: ~4 hours
```

---

## What Success Looks Like

**For Fable to succeed:**

✅ User clones repo  
✅ Runs `./start.sh` (or start.ps1)  
✅ Waits <2 minutes  
✅ Sees UI in browser  
✅ Types a question  
✅ Sees council discuss in real-time  
✅ Gets a clear decision  
✅ **ZERO docs, ZERO config, ZERO confusion**

---

## Key Changes from Previous Prompt

| Aspect | Before | After |
|--------|--------|-------|
| **Focus** | 10 deliverables (features) | Gap-fix + simplicity |
| **Gap strategy** | Assumed gaps | Audit to find real gaps |
| **Ease of use** | Mentioned | 5+ principles + scoring system |
| **Error messages** | Generic | Actionable + helpful |
| **Setup** | Docs-based | Auto-detection + defaults |
| **Testing** | Code-based | Real-world user testing |
| **Success criteria** | Feature checklist | User experience focused |

---

## How to Use This with Fable

**Simply run:**

```bash
# Copy the prompt into Fable context
cat FABLE_PROMPT.md | fable run

# Or invoke Fable directly with the markdown
fable "Read FABLE_PROMPT.md and execute the full implementation"
```

**Key things Fable will do:**

1. Read & audit the actual code (not assume)
2. Document gaps in priority order
3. Fix gaps with simplest solutions
4. Test each fix (manual + automated)
5. Create helpful error messages
6. Ship a working council

---

## Success Metrics

**When Fable finishes, verify:**

- [ ] `pytest tests/ -q` → all pass
- [ ] `./start.sh` → UI loads in <2 min
- [ ] Submit topic → see council output
- [ ] Kill Ollama → see helpful error
- [ ] `docker-compose up` → works
- [ ] All 3 phases executing
- [ ] SSE streaming live
- [ ] No cryptic errors

---

## Token Efficiency Strategy

**Fable will minimize Sonnet sub-agents by:**

✅ Reading & understanding code itself  
✅ Writing straightforward code directly  
✅ Testing with curl/pytest directly  
✅ Only using sub-agents for stuck scenarios  
✅ Aggressive pragmatism (ship v1, not perfect v2)  

**Expected cost:** <3000 tokens for entire implementation

---

## Questions This Prompt Answers

### For Fable:
- ✅ "Where do I start?" → Audit the code first
- ✅ "What should I fix first?" → Gaps in priority matrix
- ✅ "How simple is simple enough?" → Ease-of-use scoring system
- ✅ "When am I done?" → Checklists + real-world testing
- ✅ "How do I know it's good?" → Success metrics

### For Users:
- ✅ "How do I set it up?" → 1 command (./start.sh)
- ✅ "What if something breaks?" → Helpful error messages
- ✅ "How does it work?" → Minimal docs, intuitive UX

---

## Next Steps

1. ✅ **Review** this guide
2. ✅ **Review** `FABLE_PROMPT.md` (the full implementation prompt)
3. 🚀 **Invoke Fable** with the prompt
4. 📊 **Track progress** as it audits, fixes, and ships

---

**Everything is ready. Fable can start immediately.** 🚀
