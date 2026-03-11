/* __TEAM_COLORS_JS__ */

        // ─── HTML SANITIZERS (prevent XSS from data attributes / innerHTML) ───
        function _escAttr(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;').replace(/`/g,'&#96;'); }
        function _escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'); }

        // ─── RANKINGS TOGGLE ───
        function toggleRankings() {
            const body = document.getElementById('rankingsBody');
            const toggle = document.getElementById('rankingsToggle');
            const isOpen = body.style.display !== 'none';
            body.style.display = isOpen ? 'none' : 'block';
            toggle.classList.toggle('open', !isOpen);
            toggle.textContent = isOpen ? '▼' : '▲';
        }

        // ─── TAB SWITCHING ───
        const filterBtns = document.querySelectorAll('.filter-btn[data-tab]');
        const navBtns = document.querySelectorAll('.nav-btn[data-tab]');
        const tabs = document.querySelectorAll('.tab-content');

        function switchTab(tabId) {
            tabs.forEach(t => t.classList.remove('active'));
            filterBtns.forEach(b => b.classList.remove('active'));
            navBtns.forEach(b => b.classList.remove('active'));

            const target = document.getElementById('tab-' + tabId);
            if (target) target.classList.add('active');

            filterBtns.forEach(b => {
                if (b.dataset.tab === tabId) b.classList.add('active');
            });
            navBtns.forEach(b => {
                if (b.dataset.tab === tabId) b.classList.add('active');
            });

            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });
        navBtns.forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });

        // ─── SORT BUTTONS ───
        const sortBtns = document.querySelectorAll('.sort-btn');
        const matchupList = document.getElementById('matchupList');

        sortBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                sortBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const cards = Array.from(matchupList.children);
                const sort = btn.dataset.sort;

                if (sort === 'value') {
                    cards.sort((a, b) => parseFloat(b.dataset.edge) - parseFloat(a.dataset.edge));
                } else {
                    cards.sort((a, b) => parseInt(a.dataset.idx) - parseInt(b.dataset.idx));
                }
                cards.forEach(card => matchupList.appendChild(card));
            });
        });

        // ─── EXPAND / COLLAPSE LINEUPS ───
        function toggleExpand(btn) {
            const card = btn.closest('.matchup-card');
            const expanded = card.querySelector('.mc-expanded');
            const isOpen = expanded.style.display !== 'none';
            expanded.style.display = isOpen ? 'none' : 'grid';
            btn.classList.toggle('open', !isOpen);
            btn.querySelector('span').textContent = isOpen ? '▼ VIEW LINEUPS' : '▲ HIDE LINEUPS';
        }

        // ─── PLAYER BOTTOM SHEET ───
        const overlay = document.getElementById('sheetOverlay');
        const sheet = document.getElementById('bottomSheet');
        const sheetContent = document.getElementById('sheetContent');

        function buildRadarSVG(scoring, playmaking, defense, efficiency, impact) {
            // 5-axis radar chart — pure SVG, no library
            const cx = 70, cy = 70, r = 55;
            const axes = [
                {label: 'SCR', val: scoring},
                {label: 'PLY', val: playmaking},
                {label: 'DEF', val: defense},
                {label: 'EFF', val: efficiency},
                {label: 'IMP', val: impact}
            ];
            const n = axes.length;
            const angleStep = (2 * Math.PI) / n;
            const startAngle = -Math.PI / 2;

            // Grid rings at 25%, 50%, 75%, 100%
            let gridLines = '';
            [0.25, 0.5, 0.75, 1.0].forEach(pct => {
                const pts = [];
                for (let i = 0; i < n; i++) {
                    const angle = startAngle + i * angleStep;
                    pts.push((cx + r * pct * Math.cos(angle)).toFixed(1) + ',' + (cy + r * pct * Math.sin(angle)).toFixed(1));
                }
                gridLines += '<polygon points="' + pts.join(' ') + '" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="0.5"/>';
            });

            // Axis lines
            let axisLines = '';
            for (let i = 0; i < n; i++) {
                const angle = startAngle + i * angleStep;
                const x2 = cx + r * Math.cos(angle);
                const y2 = cy + r * Math.sin(angle);
                axisLines += '<line x1="' + cx + '" y1="' + cy + '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) + '" stroke="rgba(255,255,255,0.15)" stroke-width="0.5"/>';
            }

            // Data polygon
            const dataPts = [];
            for (let i = 0; i < n; i++) {
                const angle = startAngle + i * angleStep;
                const pct = Math.min((axes[i].val || 0) / 100, 1);
                dataPts.push((cx + r * pct * Math.cos(angle)).toFixed(1) + ',' + (cy + r * pct * Math.sin(angle)).toFixed(1));
            }

            // Labels
            let labels = '';
            for (let i = 0; i < n; i++) {
                const angle = startAngle + i * angleStep;
                const lx = cx + (r + 14) * Math.cos(angle);
                const ly = cy + (r + 14) * Math.sin(angle);
                labels += '<text x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) + '" text-anchor="middle" dominant-baseline="central" fill="rgba(255,255,255,0.6)" font-size="8" font-family="JetBrains Mono,monospace">' + axes[i].label + '</text>';
            }

            return '<svg viewBox="0 0 140 140" width="140" height="140" style="display:block;margin:0 auto">'
                + gridLines + axisLines
                + '<polygon points="' + dataPts.join(' ') + '" fill="rgba(0,255,85,0.15)" stroke="#00FF55" stroke-width="1.5"/>'
                + labels + '</svg>';
        }

        function openPlayerSheet(el) {
            const d = el.dataset;
            const pid = d.pid || '';
            const headshot = pid ? 'https://cdn.nba.com/headshots/nba/latest/260x190/' + pid + '.png' : '';
            const netVal = parseFloat(d.net || 0);
            const netColor = netVal >= 0 ? '#00FF55' : '#FF3333';
            const netSign = netVal >= 0 ? '+' : '';
            const dsVal = parseInt(d.mojo || 50);
            const dsColor = dsVal >= 83 ? '#00FF55' : dsVal >= 67 ? '#4CAF50' : dsVal >= 52 ? '#FF9800' : '#FF3333';

            // Team color lookup
            const teamColors = TEAM_COLORS_JS;
            const tc = teamColors[d.team] || '#333';

            // Parse top pairs
            let topPairs = [];
            try { topPairs = JSON.parse((d.topPairs || '[]').replace(/&quot;/g, '"')); } catch(e) {}
            const pairsHtml = topPairs.length > 0 ? topPairs.map((p, i) =>
                '<div class="sheet-pair-row"><span class="sheet-pair-rank">' + (i+1) + '</span><span class="sheet-pair-name">' + p + '</span></div>'
            ).join('') : '<div class="sheet-pair-row" style="opacity:0.4">No pair data available</div>';

            // Radar chart
            const radarSVG = buildRadarSVG(
                parseFloat(d.scoringPct || 0),
                parseFloat(d.playmakingPct || 0),
                parseFloat(d.defensePct || 0),
                parseFloat(d.efficiencyPct || 0),
                parseFloat(d.impactPct || 0)
            );

            // Injury delta section
            const injDelta = parseInt(d.injDelta || 0);
            const roleContext = injDelta !== 0
                ? '<div class="sheet-role-badge" style="background:' + (injDelta > 0 ? 'rgba(0,204,68,0.15);color:#00CC44' : 'rgba(255,51,51,0.15);color:#FF3333') + '">'
                  + (injDelta > 0 ? '▲ ELEVATED' : '▼ REDUCED') + ' ROLE (' + (injDelta > 0 ? '+' : '') + injDelta + ' MOJO)</div>'
                : '<div class="sheet-role-badge" style="background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.4)">STANDARD ROLE</div>';

            sheetContent.innerHTML = `
                <div class="sheet-header" style="border-left:3px solid ${tc}">
                    ${headshot ? '<img src="' + headshot + '" class="sheet-face" onerror="this.style.display=\'none\'">' : ''}
                    <div>
                        <div class="sheet-name">${d.name || '—'}</div>
                        <div class="sheet-arch-badge" style="border-color:${tc};color:${tc}">${d.arch || '—'}</div>
                        <div class="sheet-meta-sub">${d.team || '—'} · ${d.mpg || '—'} MPG · MOJO Range ${d.range || '—'}</div>
                    </div>
                    <div style="margin-left:auto;text-align:center">
                        <div class="sheet-mojo" style="color:${dsColor}">${d.mojo || '—'}</div>
                        <div class="sheet-mojo-label">MOJO</div>
                    </div>
                </div>

                ${roleContext}

                <div class="sheet-radar-section">
                    <div class="sheet-section">MOJO BREAKDOWN</div>
                    ${radarSVG}
                </div>

                <div class="sheet-section">STAT LINE</div>
                <div class="sheet-stat-grid">
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.pts || '—'}</div><div class="sheet-stat-lbl">PTS</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.ast || '—'}</div><div class="sheet-stat-lbl">AST</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.reb || '—'}</div><div class="sheet-stat-lbl">REB</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.ts || '—'}%</div><div class="sheet-stat-lbl">TS%</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.usg || '—'}%</div><div class="sheet-stat-lbl">USG</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num" style="color:${netColor}">${netSign}${netVal.toFixed(1)}</div><div class="sheet-stat-lbl">NET</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.stl || '—'}</div><div class="sheet-stat-lbl">STL</div></div>
                    <div class="sheet-stat-cell"><div class="sheet-stat-num">${d.blk || '—'}</div><div class="sheet-stat-lbl">BLK</div></div>
                </div>

                <div class="sheet-section">TOP WOWY PARTNERS</div>
                <div class="sheet-pairs-container">
                    ${pairsHtml}
                </div>

                <div class="sheet-section">CONTEXT FACTORS</div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">WOWY Impact</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.soloImpact || 50, 100)}%; background:#6366F1"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.soloImpact || 50)}</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Pair Synergy</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.synScore || 50, 100)}%; background:#F59E0B"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.synScore || 50)}</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Archetype Fit</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.fitScore || 50, 100)}%; background:#10B981"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.fitScore || 50)}</span>
                </div>

                ${parseFloat(d.waste || 0) > 5 || parseInt(d.mojoGap || 0) > 5 ? '<div class="sheet-section">SCOUTING INTEL</div>' +
                    (parseFloat(d.waste || 0) > 5 ? '<div class="sheet-intel-row"><span class="sheet-intel-label">Teammate Waste</span><span class="sheet-intel-val" style="color:' + (parseFloat(d.waste) >= 40 ? '#FF3333' : parseFloat(d.waste) >= 20 ? '#FFB300' : '#8e8e8e') + '">' + parseFloat(d.waste).toFixed(1) + '</span><span class="sheet-intel-sub">Less efficient teammates consuming possessions</span></div>' : '') +
                    (parseInt(d.mojoGap || 0) > 5 ? '<div class="sheet-intel-row"><span class="sheet-intel-label">MOJO Upside</span><span class="sheet-intel-val" style="color:#00c6ff">+' + parseInt(d.mojoGap || 0) + '</span><span class="sheet-intel-sub">Potential MOJO in an expanded role</span></div>' : '') +
                    (parseInt(d.roleMismatch || 0) === 1 ? '<div class="sheet-intel-badge" style="background:rgba(255,179,0,0.15);color:#FFB300;font-size:10px;padding:4px 8px;border-radius:4px;margin-top:4px;font-weight:700;letter-spacing:0.5px">ROLE MISMATCH DETECTED</div>' : '') +
                    (d.intel ? '<div class="sheet-intel-notes">' + _escHtml(d.intel) + '</div>' : '')
                : ''}
            `;

            overlay.classList.add('show');
            sheet.classList.add('show');
        }

        overlay.addEventListener('click', closeSheet);
        function closeSheet() {
            overlay.classList.remove('show');
            sheet.classList.remove('show');
        }

        // Close on swipe down
        let sheetStartY = 0;
        sheet.addEventListener('touchstart', e => {
            sheetStartY = e.touches[0].clientY;
        });
        sheet.addEventListener('touchmove', e => {
            const diff = e.touches[0].clientY - sheetStartY;
            if (diff > 80) closeSheet();
        });

        // ─── SIM ENGINE (v2 — three-col, position slots, per-player MPG) ───
        const simState = {
            home: { team: '', court: [], bench: [], locker: [] },
            away: { team: '', court: [], bench: [], locker: [] },
        };
        let simDragPid = null;
        let simDragSrcSide = null;
        let simDragSrcZone = null;
        const simPlayerMinutes = {};  // pid → custom minutes
        const simAdjustedMojo = {};   // pid → adjusted MOJO after usage redistribution
        function simGetTeamLogo(abbr) {
            if (!SIM_DATA || !SIM_DATA.team_ids) return '';
            const tid = SIM_DATA.team_ids[abbr] || 0;
            return 'https://cdn.nba.com/logos/nba/' + tid + '/global/L/logo.svg';
        }

        // ─── TEAM LOGO GRID SELECTOR ───
        let simGridSide = null;
        function simOpenTeamGrid(side) {
            simGridSide = side;
            const overlay = document.getElementById('simTeamGridOverlay');
            const title = document.getElementById('simTeamGridTitle');
            const grid = document.getElementById('simTeamGrid');
            title.textContent = 'SELECT ' + side.toUpperCase() + ' TEAM';

            // Build grid items from all teams
            const teams = Object.keys(SIM_DATA.rosters || {}).sort();
            let html = '';
            teams.forEach(abbr => {
                const logo = simGetTeamLogo(abbr);
                html += '<div class="sim-team-grid-item" onclick="simPickTeam(\'' + abbr + '\')">' +
                    '<img src="' + logo + '" alt="' + abbr + '">' +
                    '<span>' + abbr + '</span></div>';
            });
            grid.innerHTML = html;
            overlay.style.display = 'flex';
        }
        function simCloseTeamGrid() {
            document.getElementById('simTeamGridOverlay').style.display = 'none';
            simGridSide = null;
        }
        function simPickTeam(abbr) {
            if (!simGridSide) return;
            const side = simGridSide;
            // Set the hidden select and trigger change
            const sel = document.getElementById(side === 'home' ? 'simHomeTeam' : 'simAwayTeam');
            sel.value = abbr;
            sel.dispatchEvent(new Event('change'));
            simCloseTeamGrid();
        }
        function simUpdateTeamBtn(side) {
            const abbr = simState[side].team;
            const btn = document.getElementById(side === 'home' ? 'simHomeBtnDisplay' : 'simAwayBtnDisplay');
            const logo = document.getElementById(side === 'home' ? 'simHomeBtnLogo' : 'simAwayBtnLogo');
            const text = document.getElementById(side === 'home' ? 'simHomeBtnText' : 'simAwayBtnText');
            if (abbr) {
                logo.src = simGetTeamLogo(abbr);
                logo.style.display = 'block';
                text.textContent = abbr + ' — ' + (SIM_DATA.team_names[abbr] || abbr);
                btn.classList.add('selected');
            } else {
                logo.style.display = 'none';
                text.textContent = 'Select team...';
                btn.classList.remove('selected');
            }
        }

        function simGetPlayerById(pid) {
            for (const team in SIM_DATA.rosters) {
                for (const p of SIM_DATA.rosters[team]) {
                    if (p.id === pid) return p;
                }
            }
            return null;
        }

        function simToggleLocker(side) {
            const zone = document.getElementById(side === 'home' ? 'simHomeLockerZone' : 'simAwayLockerZone');
            const arrow = document.getElementById(side === 'home' ? 'simHomeLockerArrow' : 'simAwayLockerArrow');
            const isOpen = zone.style.display !== 'none';
            zone.style.display = isOpen ? 'none' : 'flex';
            arrow.classList.toggle('open', !isOpen);
        }

        function simCardTier(mojo) {
            if (mojo >= 80) return 'tier-gold';
            if (mojo >= 60) return 'tier-silver';
            if (mojo >= 40) return 'tier-bronze';
            return 'tier-base';
        }

        function simBuildCard(pid, side) {
            const p = simGetPlayerById(pid);
            if (!p) return '';
            const mojo = simAdjustedMojo[pid] !== undefined ? simAdjustedMojo[pid] : p.mojo;
            const tier = simCardTier(mojo);
            const headshot = 'https://cdn.nba.com/headshots/nba/latest/260x190/' + pid + '.png';
            const lastName = p.name.split(' ').pop();
            const archLabel = (p.arch_icon || '') + ' ' + (p.archetype || '');
            return '<div class="sim-card ' + tier + '" draggable="true" data-pid="' + pid + '" data-side="' + side + '"' +
                ' ontouchstart="simTouchStart(event)" ontouchmove="simTouchMove(event)" ontouchend="simTouchEnd(event)">' +
                '<div class="sim-card-inner">' +
                '<div class="sim-card-grip">&#x283F;</div>' +
                '<div class="sim-card-header">' +
                '<div class="sim-card-mojo">' + Math.round(mojo) + '</div>' +
                '<span class="sim-card-pos">' + (p.pos || 'WING') + '</span>' +
                '</div>' +
                '<img class="sim-card-face" src="' + headshot + '" onerror="this.style.display=\'none\'" alt="">' +
                '<div class="sim-card-info" onclick="simCardClick(' + pid + ',event)">' +
                '<div class="sim-card-name">' + lastName + '</div>' +
                '<div class="sim-card-arch">' + archLabel.trim() + '</div>' +
                '<div class="sim-card-stats">' +
                '<div class="sim-card-stat"><div class="sim-card-stat-label">PTS</div><div class="sim-card-stat-val">' + (p.pts || 0) + '</div></div>' +
                '<div class="sim-card-stat"><div class="sim-card-stat-label">AST</div><div class="sim-card-stat-val">' + (p.ast || 0) + '</div></div>' +
                '<div class="sim-card-stat"><div class="sim-card-stat-label">REB</div><div class="sim-card-stat-val">' + (p.reb || 0) + '</div></div>' +
                '</div></div></div></div>';
        }

        function simMpgChange(pid, val, side) {
            simPlayerMinutes[pid] = parseInt(val);
            // Update the rotation editor val display (slider is in center hub now)
            const rotRows = document.querySelectorAll('.sim-rot-row');
            rotRows.forEach(r => {
                const slider = r.querySelector('input[type="range"]');
                if (slider && slider.oninput && slider.oninput.toString().includes(pid)) {
                    const valSpan = r.querySelector('.sim-rot-val');
                    if (valSpan) valSpan.textContent = val;
                }
            });
            // Also update any mpg-val elements (legacy)
            const cards = document.querySelectorAll('.sim-card[data-pid="'+pid+'"]');
            cards.forEach(c => {
                const v = c.querySelector('.mpg-val');
                if (v) v.textContent = val;
            });
            simRecalc();
            // Re-render rotation editor to update totals
            simRenderRotationEditor();
        }

        function simTeamChange(side) {
            const sel = document.getElementById(side === 'home' ? 'simHomeTeam' : 'simAwayTeam');
            const abbr = sel.value;
            simState[side].team = abbr;
            simState[side].court = [];
            simState[side].bench = [];
            simState[side].locker = [];

            if (abbr && SIM_DATA.rosters[abbr]) {
                // Auto-fill: 2G + 2W + 1B by MPG, overflow fills remaining
                const roster = [...SIM_DATA.rosters[abbr]].sort((a,b) => b.mpg - a.mpg);
                const posSlots = { GUARD: 2, WING: 2, BIG: 1 };
                const posCounts = { GUARD: 0, WING: 0, BIG: 0 };
                // First pass: fill by position
                roster.forEach(p => {
                    const pos = p.pos || 'WING';
                    if (posCounts[pos] < posSlots[pos] && simState[side].court.length < 5) {
                        simState[side].court.push(p.id);
                        posCounts[pos]++;
                        simPlayerMinutes[p.id] = Math.round(p.mpg) || 32;
                    }
                });
                // If we don't have 5 yet, fill remaining court spots
                roster.forEach(p => {
                    if (simState[side].court.length < 5 && !simState[side].court.includes(p.id)) {
                        simState[side].court.push(p.id);
                        simPlayerMinutes[p.id] = Math.round(p.mpg) || 28;
                    }
                });
                // Next 4 to bench, rest to locker
                roster.forEach(p => {
                    if (!simState[side].court.includes(p.id)) {
                        if (simState[side].bench.length < 4) {
                            simState[side].bench.push(p.id);
                            simPlayerMinutes[p.id] = Math.round(p.mpg) || 16;
                        } else {
                            simState[side].locker.push(p.id);
                            simPlayerMinutes[p.id] = 0;
                        }
                    }
                });
            }

            // Update header
            const logo = document.getElementById(side === 'home' ? 'simHomeLogo' : 'simAwayLogo');
            const label = document.getElementById(side === 'home' ? 'simHomeLabel' : 'simAwayLabel');
            if (abbr) {
                logo.src = simGetTeamLogo(abbr);
                label.textContent = abbr;
                const col = SIM_DATA.team_colors[abbr] || '#333';
                document.getElementById(side === 'home' ? 'simHomeHeader' : 'simAwayHeader').style.borderBottomColor = col;
            } else {
                logo.src = '';
                label.textContent = side.toUpperCase();
            }
            // Update rotation tab logo
            const rotLogo = document.getElementById(side === 'home' ? 'simRotLogoHome' : 'simRotLogoAway');
            if (rotLogo) {
                if (abbr) { rotLogo.src = simGetTeamLogo(abbr); rotLogo.style.display = ''; }
                else { rotLogo.src = ''; rotLogo.style.display = 'none'; }
            }

            // Show schemes in center column
            simUpdateSchemes(side);
            // Update HCA badge
            simUpdateHca();
            // Update the team button display
            simUpdateTeamBtn(side);

            simRenderAll(side);
            simRecalc();
            simCheckReady();
            // Show onboarding banner if both teams loaded and not previously dismissed
            if (simState.home.team && simState.away.team) simShowOnboard();
        }

        function simShowOnboard() {
            if (localStorage.getItem('sim_onboard_seen')) return;
            const h = document.getElementById('simOnboardHome');
            const a = document.getElementById('simOnboardAway');
            if (h) h.style.display = 'flex';
            if (a) a.style.display = 'flex';
        }
        function simDismissOnboard() {
            localStorage.setItem('sim_onboard_seen', '1');
            const h = document.getElementById('simOnboardHome');
            const a = document.getElementById('simOnboardAway');
            if (h) h.style.display = 'none';
            if (a) a.style.display = 'none';
        }

        // ─── COACHES DICT ───
        const SIM_COACHES = {
            ATL:"Snyder", BOS:"Mazzulla", BKN:"Fernandez",
            CHA:"Lee", CHI:"Donovan", CLE:"Atkinson",
            DAL:"Kidd", DEN:"Malone", DET:"Bickerstaff",
            GSW:"Kerr", HOU:"Udoka", IND:"Carlisle",
            LAC:"Lue", LAL:"Redick", MEM:"Jenkins",
            MIA:"Spoelstra", MIL:"Rivers", MIN:"Finch",
            NOP:"Green", NYK:"Thibodeau", OKC:"Daigneault",
            ORL:"Mosley", PHI:"Nurse", PHX:"Budenholzer",
            POR:"Billups", SAC:"Brown", SAS:"Popovich",
            TOR:"Rajakovic", UTA:"Hardy", WAS:"Keefe"
        };

        function simUpdateSchemes(side) {
            const abbr = simState[side].team;
            const el = document.getElementById(side === 'home' ? 'simHomeSchemes' : 'simAwaySchemes');
            if (!abbr || !SIM_DATA.team_stats[abbr]) { el.innerHTML = ''; return; }
            const ts = SIM_DATA.team_stats[abbr];
            const coach = SIM_COACHES[abbr] || '';
            const coachHtml = coach ? '<span class="sim-scheme-coach">' + coach + ':</span> ' : '';
            const off = ts.off_scheme || 'Balanced';
            const def = ts.def_scheme || 'Standard';
            el.innerHTML = '<span class="sim-scheme-pill">' + coachHtml + off.toUpperCase() + '</span>' +
                           '<span class="sim-scheme-pill">' + coachHtml + def.toUpperCase() + '</span>';
        }

        // ─── LINK MODE ───
        let simLinkModeActive = true;
        let simSelectedLinks = new Set();
        let simSelectedPlayer = null;  // single player card click
        let simActiveRotTab = 'home';

        function simToggleLinkMode() {
            simLinkModeActive = !simLinkModeActive;
            const btn = document.getElementById('simLinkToggle');
            btn.classList.toggle('active', simLinkModeActive);
            const inspector = document.getElementById('simComboInspector');
            inspector.style.display = simLinkModeActive ? 'block' : 'none';
            // Toggle link-mode-active on courts so cards pass through clicks to overlay
            const homeCourt = document.getElementById('simHomeCourt');
            const awayCourt = document.getElementById('simAwayCourt');
            if (homeCourt) homeCourt.classList.toggle('link-mode-active', simLinkModeActive);
            if (awayCourt) awayCourt.classList.toggle('link-mode-active', simLinkModeActive);
            if (simLinkModeActive) {
                simRenderLinks('home');
                simRenderLinks('away');
            } else {
                simSelectedLinks.clear();
                document.getElementById('simHomeLinkOverlay').innerHTML = '';
                document.getElementById('simAwayLinkOverlay').innerHTML = '';
                simUpdateComboInspector();
            }
        }

        function simGetSlotCenter(side, pos, slot) {
            const court = document.getElementById(side === 'home' ? 'simHomeCourt' : 'simAwayCourt');
            const el = court.querySelector('.sim-pos-slot[data-pos="'+pos+'"][data-slot="'+slot+'"]');
            if (!el || !court) return null;
            const cr = court.getBoundingClientRect();
            const sr = el.getBoundingClientRect();
            return {
                x: (sr.left + sr.width/2 - cr.left) / cr.width * 100,
                y: (sr.top + sr.height/2 - cr.top) / cr.height * 100
            };
        }

        function simRenderLinks(side) {
            if (!simLinkModeActive) return;
            const overlay = document.getElementById(side === 'home' ? 'simHomeLinkOverlay' : 'simAwayLinkOverlay');
            const pids = simState[side].court;
            if (pids.length < 2) { overlay.innerHTML = ''; return; }
            const pairs = SIM_DATA.pairs || {};

            // Map pid → slot position for line coordinates
            const slots = document.querySelectorAll('.sim-pos-slot[data-side="'+side+'"]');
            const pidSlots = {};
            slots.forEach(s => {
                const card = s.querySelector('.sim-card');
                if (card) {
                    const pid = parseInt(card.dataset.pid);
                    const court = s.closest('.sim-court');
                    const cr = court.getBoundingClientRect();
                    const sr = s.getBoundingClientRect();
                    pidSlots[pid] = {
                        x: ((sr.left + sr.width/2 - cr.left) / cr.width * 100).toFixed(1),
                        y: ((sr.top + sr.height/2 - cr.top) / cr.height * 100).toFixed(1)
                    };
                }
            });

            let svg = '';
            for (let i = 0; i < pids.length; i++) {
                for (let j = i + 1; j < pids.length; j++) {
                    const a = pids[i], b = pids[j];
                    const pa = pidSlots[a], pb = pidSlots[b];
                    if (!pa || !pb) continue;
                    const key1 = a + '-' + b, key2 = b + '-' + a;
                    const pairData = pairs[key1] || pairs[key2];
                    const nrtg = pairData ? pairData.nrtg : 0;
                    const poss = pairData ? (pairData.poss || 0) : 0;

                    let color = '#FFD700'; // yellow default
                    if (nrtg > 3) color = '#00FF55';
                    else if (nrtg < -1) color = '#FF4444';

                    const pairKey = Math.min(a,b) + '-' + Math.max(a,b);
                    const selected = simSelectedLinks.has(pairKey);
                    const lowSample = poss < 50;

                    const lineCoords = 'x1="' + pa.x + '%" y1="' + pa.y + '%" x2="' + pb.x + '%" y2="' + pb.y + '%"';

                    // Visual line (visible, no pointer events)
                    svg += '<line ' + lineCoords +
                        ' stroke="' + color + '"' +
                        ' class="link-visual' + (selected ? ' link-selected' : '') + (lowSample ? ' link-low-sample' : '') + '"' +
                        ' data-pair="' + pairKey + '" />';

                    // Hit-area line (invisible fat target for clicking)
                    svg += '<line ' + lineCoords +
                        ' stroke="transparent"' +
                        ' class="link-hitarea"' +
                        ' data-pair="' + pairKey + '" data-side="' + side + '"' +
                        ' data-nrtg="' + nrtg + '" data-poss="' + poss + '"' +
                        ' data-pida="' + a + '" data-pidb="' + b + '" />';
                }
            }
            overlay.innerHTML = svg;

            // Add click + hover handlers (on hit-area lines)
            overlay.querySelectorAll('line.link-hitarea').forEach(hitLine => {
                // CLICK to select/deselect link
                hitLine.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const pk = this.dataset.pair;
                    if (pk) simLinkClick(pk);
                });
                hitLine.addEventListener('mouseenter', function(e) {
                    const tooltip = document.getElementById(side === 'home' ? 'simHomeLinkTooltip' : 'simAwayLinkTooltip');
                    const pA = simGetPlayerById(parseInt(this.dataset.pida));
                    const pB = simGetPlayerById(parseInt(this.dataset.pidb));
                    const nrtg = parseFloat(this.dataset.nrtg);
                    const poss = parseInt(this.dataset.poss);
                    const sign = nrtg >= 0 ? '+' : '';
                    tooltip.innerHTML = (pA ? pA.name.split(' ').pop() : '?') + ' + ' +
                        (pB ? pB.name.split(' ').pop() : '?') + ': ' +
                        '<strong style="color:' + (nrtg >= 0 ? '#00FF55' : '#FF4444') + '">' + sign + nrtg.toFixed(1) + ' NRtg</strong>' +
                        ' <span style="opacity:0.5">(' + poss + ' poss)</span>';
                    tooltip.style.display = 'block';
                    const court = tooltip.closest('.sim-court');
                    const cr = court.getBoundingClientRect();
                    tooltip.style.left = (e.clientX - cr.left + 10) + 'px';
                    tooltip.style.top = (e.clientY - cr.top - 30) + 'px';
                    // Highlight corresponding visual line
                    const visual = overlay.querySelector('line.link-visual[data-pair="' + this.dataset.pair + '"]');
                    if (visual) visual.classList.add('link-hover');
                });
                hitLine.addEventListener('mouseleave', function() {
                    const tooltip = document.getElementById(side === 'home' ? 'simHomeLinkTooltip' : 'simAwayLinkTooltip');
                    tooltip.style.display = 'none';
                    // Remove hover highlight
                    const visual = overlay.querySelector('line.link-visual[data-pair="' + this.dataset.pair + '"]');
                    if (visual) visual.classList.remove('link-hover');
                });
            });
        }

        function simCardClick(pid, e) {
            e.stopPropagation();
            simSelectedPlayer = (simSelectedPlayer === pid) ? null : pid;
            simSelectedLinks.clear();
            simRenderLinks('home');
            simRenderLinks('away');
            simUpdateComboInspector();
        }

        function simLinkClick(pairKey) {
            simSelectedPlayer = null;
            if (simSelectedLinks.has(pairKey)) {
                simSelectedLinks.delete(pairKey);
            } else {
                simSelectedLinks.add(pairKey);
            }
            simRenderLinks('home');
            simRenderLinks('away');
            simUpdateComboInspector();
        }

        function simWowyChip(pid) {
            const p = simGetPlayerById(pid);
            if (!p) return '<span class="sim-wowy-chip">#' + pid + '</span>';
            const hs = 'https://cdn.nba.com/headshots/nba/latest/260x190/' + pid + '.png';
            const last = p.name.split(' ').pop();
            return '<span class="sim-wowy-chip"><img class="sim-wowy-chip-img" src="' + hs + '" onerror="this.style.display=\'none\'" alt="">' + last + '</span>';
        }

        function simWowyStatCell(val, isDiff) {
            if (val === null || val === undefined) return '<td class="sim-wowy-cell">—</td>';
            const n = parseFloat(val);
            const cls = isDiff ? (n >= 0 ? 'pos' : 'neg') : '';
            const sign = (isDiff && n >= 0) ? '+' : '';
            return '<td class="sim-wowy-cell ' + cls + '">' + sign + n.toFixed(1) + '</td>';
        }

        function simUpdateComboInspector() {
            const content = document.getElementById('simComboContent');

            // ─── Single player selected via card click ───
            if (simSelectedPlayer) {
                const p = simGetPlayerById(simSelectedPlayer);
                if (!p) { content.innerHTML = '<div class="sim-combo-empty">Player not found</div>'; return; }
                let html = '<div class="sim-wowy-header">' + simWowyChip(simSelectedPlayer) + '</div>';
                html += '<table class="sim-wowy-table"><thead><tr><th></th><th>OFF</th><th>DEF</th><th>NET</th></tr></thead><tbody>';
                const rapm = p.rapm != null ? p.rapm.toFixed(1) : null;
                const rapmOff = p.rapm_off != null ? p.rapm_off.toFixed(1) : null;
                const rapmDef = p.rapm_def != null ? p.rapm_def.toFixed(1) : null;
                html += '<tr><td class="sim-wowy-label">RAPM</td>';
                html += simWowyStatCell(rapmOff, true) + simWowyStatCell(rapmDef, true) + simWowyStatCell(rapm, true);
                html += '</tr>';
                html += '<tr><td class="sim-wowy-label">PER GAME</td>';
                html += '<td class="sim-wowy-cell">' + (p.pts||0) + '/' + (p.ast||0) + '/' + (p.reb||0) + '</td>';
                html += '<td class="sim-wowy-cell">' + (p.stl||0) + ' stl / ' + (p.blk||0) + ' blk</td>';
                html += '<td class="sim-wowy-cell">' + (p.mpg||0) + ' mpg</td>';
                html += '</tr>';
                html += '</tbody></table>';
                content.innerHTML = html;
                return;
            }

            // ─── No links selected ───
            if (simSelectedLinks.size === 0) {
                content.innerHTML = '<div class="sim-combo-empty">Click a synergy line or player card</div>';
                return;
            }

            // ─── Extract unique players from selected links ───
            const playerSet = new Set();
            simSelectedLinks.forEach(key => {
                key.split('-').forEach(id => playerSet.add(Number(id)));
            });
            const pids = Array.from(playerSet).sort((a,b) => a - b);
            const n = pids.length;
            const pairs = SIM_DATA.pairs || {};
            let html = '';

            // ─── Build header with player chips ───
            html += '<div class="sim-wowy-header">';
            html += '<span class="sim-wowy-group-label">' + n + '-MAN</span>';
            pids.forEach(pid => { html += simWowyChip(pid); });
            html += '</div>';

            // ─── Group combo lookup (2-5 man) ───
            const comboKey = pids.join('-');
            const comboSrc = n <= 5 ? (SIM_DATA['combos_' + n] || {}) : {};
            const cd = comboSrc[comboKey];

            if (cd) {
                html += '<table class="sim-wowy-table"><thead><tr><th></th><th>MIN</th><th>OFF</th><th>DEF</th><th>NET</th></tr></thead><tbody>';
                html += '<tr><td class="sim-wowy-label">COMBO</td>';
                html += simWowyStatCell(cd.min, false);
                html += simWowyStatCell(cd.ortg, false);
                html += simWowyStatCell(cd.drtg, false);
                html += simWowyStatCell(cd.nrtg, true);
                html += '</tr>';
                html += '<tr><td class="sim-wowy-label">GP</td><td class="sim-wowy-cell">' + (cd.gp||0) + '</td><td colspan="3"></td></tr>';
                html += '</tbody></table>';
            } else if (n > 2) {
                html += '<div class="sim-combo-empty">No ' + n + '-man combo data</div>';
            }

            // ─── Individual pair breakdowns ───
            if (n >= 2) {
                html += '<div class="sim-wowy-pairs">';
                for (let i = 0; i < pids.length; i++) {
                    for (let j = i + 1; j < pids.length; j++) {
                        const a = pids[i], b = pids[j];
                        const pk1 = a + '-' + b, pk2 = b + '-' + a;
                        const pd = pairs[pk1] || pairs[pk2];
                        const c2key = [a,b].sort((x,y)=>x-y).join('-');
                        const c2 = (SIM_DATA.combos_2 || {})[c2key];
                        const pA = simGetPlayerById(a), pB = simGetPlayerById(b);
                        const nA = pA ? pA.name.split(' ').pop() : '#'+a;
                        const nB = pB ? pB.name.split(' ').pop() : '#'+b;

                        html += '<div class="sim-wowy-pair-row">';
                        html += '<span class="sim-wowy-pair-names">' + nA + ' + ' + nB + '</span>';
                        if (c2) {
                            const nCls = c2.nrtg >= 0 ? 'pos' : 'neg';
                            const nSgn = c2.nrtg >= 0 ? '+' : '';
                            html += '<span class="sim-wowy-pair-stat">MIN ' + c2.min + '</span>';
                            html += '<span class="sim-wowy-pair-stat">OFF ' + c2.ortg + '</span>';
                            html += '<span class="sim-wowy-pair-stat">DEF ' + c2.drtg + '</span>';
                            html += '<span class="sim-wowy-pair-stat ' + nCls + '">NET ' + nSgn + c2.nrtg + '</span>';
                        } else if (pd) {
                            const nCls = pd.nrtg >= 0 ? 'pos' : 'neg';
                            const nSgn = pd.nrtg >= 0 ? '+' : '';
                            html += '<span class="sim-wowy-pair-stat ' + nCls + '">NRtg ' + nSgn + pd.nrtg.toFixed(1) + '</span>';
                        }
                        if (pd && pd.syn != null) html += '<span class="sim-wowy-pair-stat syn">SYN ' + pd.syn + '</span>';
                        html += '</div>';
                    }
                }
                html += '</div>';
            }

            content.innerHTML = html;
        }

        // ─── ROTATION EDITOR ───
        function simSwitchRotTab(side) {
            simActiveRotTab = side;
            document.getElementById('simRotTabHome').classList.toggle('active', side === 'home');
            document.getElementById('simRotTabAway').classList.toggle('active', side === 'away');
            simRenderRotationEditor();
        }

        function simRenderRotationEditor() {
            const section = document.getElementById('simRotationSection');
            const content = document.getElementById('simRotationContent');
            const hasBoth = simState.home.team && simState.away.team;
            section.style.display = hasBoth ? 'block' : 'none';
            if (!hasBoth) return;

            const side = simActiveRotTab;
            const abbr = simState[side].team;
            if (!abbr) { content.innerHTML = ''; return; }

            let html = '';
            let totalMin = 0;

            // Starters
            if (simState[side].court.length > 0) {
                html += '<div class="sim-rot-group-label">STARTERS</div>';
                simState[side].court.forEach(pid => {
                    html += simBuildRotRow(pid, side);
                    totalMin += (simPlayerMinutes[pid] || 0);
                });
            }
            // Bench
            if (simState[side].bench.length > 0) {
                html += '<div class="sim-rot-group-label">BENCH</div>';
                simState[side].bench.forEach(pid => {
                    html += simBuildRotRow(pid, side);
                    totalMin += (simPlayerMinutes[pid] || 0);
                });
            }

            // Total minutes
            const warn = totalMin > 250 || totalMin < 200;
            html += '<div class="sim-rot-total' + (warn ? ' warn' : '') + '">' +
                '<span>TOTAL</span><span>' + totalMin + ' / 240</span></div>';

            content.innerHTML = html;
        }

        function simBuildRotRow(pid, side) {
            const p = simGetPlayerById(pid);
            if (!p) return '';
            const mojo = simAdjustedMojo[pid] !== undefined ? simAdjustedMojo[pid] : p.mojo;
            const mpg = simPlayerMinutes[pid] !== undefined ? simPlayerMinutes[pid] : Math.round(p.mpg);
            const headshot = 'https://cdn.nba.com/headshots/nba/latest/260x190/' + pid + '.png';
            const mojoColor = mojo >= 80 ? '#FFD700' : mojo >= 60 ? '#c0c0c0' : mojo >= 40 ? '#CD7F32' : 'rgba(0,0,0,0.3)';
            return '<div class="sim-rot-row">' +
                '<img class="sim-rot-face" src="' + headshot + '" onerror="this.style.display=\'none\'" alt="">' +
                '<span class="sim-rot-name">' + p.name.split(' ').pop() + '</span>' +
                '<span class="sim-rot-pos">' + (p.pos || 'W') + '</span>' +
                '<span class="sim-rot-mojo" style="color:' + mojoColor + '">' + Math.round(mojo) + '</span>' +
                '<input type="range" class="sim-rot-slider" min="0" max="48" value="' + mpg + '" oninput="simMpgChange(' + pid + ',this.value,\''+side+'\')">' +
                '<span class="sim-rot-val">' + mpg + '</span>' +
                '</div>';
        }

        function simUpdateHca() {
            const badge = document.getElementById('simHcaBadge');
            const venue = document.getElementById('simVenue').value;
            const homeAbbr = simState.home.team;
            if (venue === 'home' && homeAbbr) {
                const hca = (SIM_DATA.team_hca && SIM_DATA.team_hca[homeAbbr]) ? SIM_DATA.team_hca[homeAbbr] : 1.8;
                badge.textContent = '+' + hca.toFixed(1) + ' HCA';
            } else {
                badge.textContent = 'NEUTRAL';
            }
        }
        document.getElementById('simVenue').addEventListener('change', function() { simUpdateHca(); });

        // ─── RENDER FUNCTIONS ───
        function simRenderAll(side) {
            const sides = side ? [side] : ['home', 'away'];
            sides.forEach(s => {
                simRenderCourt(s);
                simRenderBench(s);
                simRenderLocker(s);
            });
            // Attach dragstart to all cards
            setTimeout(() => {
                document.querySelectorAll('.sim-card[draggable="true"]').forEach(card => {
                    card.addEventListener('dragstart', simDragStart);
                    card.addEventListener('dragend', simDragEnd);
                });
                // Re-render links after DOM settles
                if (simLinkModeActive) {
                    simRenderLinks('home');
                    simRenderLinks('away');
                    // Ensure link-mode-active class is on courts for click pass-through
                    const hc = document.getElementById('simHomeCourt');
                    const ac = document.getElementById('simAwayCourt');
                    if (hc) hc.classList.add('link-mode-active');
                    if (ac) ac.classList.add('link-mode-active');
                }
            }, 50);
            // Update rotation editor
            simRenderRotationEditor();
        }

        function simRenderCourt(side) {
            const slots = document.querySelectorAll('.sim-pos-slot[data-side="'+side+'"]');
            const courtPids = simState[side].court;
            // Group by position: GUARD, WING, BIG
            const groups = { GUARD: [], WING: [], BIG: [] };
            const unassigned = [];
            courtPids.forEach(pid => {
                const p = simGetPlayerById(pid);
                const pos = p ? (p.pos || 'WING') : 'WING';
                if (groups[pos] && groups[pos].length < 2) { groups[pos].push(pid); }
                else if (pos === 'BIG' && groups.BIG.length < 1) { groups.BIG.push(pid); }
                else { unassigned.push(pid); }
            });
            // Fill empty slots with overflow
            ['GUARD','WING','BIG'].forEach(pos => {
                const max = pos === 'BIG' ? 1 : 2;
                while (groups[pos].length < max && unassigned.length > 0) {
                    groups[pos].push(unassigned.shift());
                }
            });
            // Assign to HTML slots by data-pos + data-slot
            const slotAssign = {};
            ['GUARD','WING','BIG'].forEach(pos => {
                groups[pos].forEach((pid, i) => { slotAssign[pos + '_' + (i+1)] = pid; });
            });
            slots.forEach(slot => {
                const pos = slot.dataset.pos;
                const slotNum = slot.dataset.slot || '1';
                const key = pos + '_' + slotNum;
                const pid = slotAssign[key];
                const label = pos === 'GUARD' ? 'G' : pos === 'WING' ? 'W' : 'B';
                if (pid) {
                    slot.innerHTML = simBuildCard(pid, side);
                    slot.classList.add('filled');
                } else {
                    slot.innerHTML = '<span class="sim-pos-label">' + label + '</span>';
                    slot.classList.remove('filled');
                }
            });
        }

        function simRenderBench(side) {
            const zone = document.getElementById(side === 'home' ? 'simHomeBenchZone' : 'simAwayBenchZone');
            const count = document.getElementById(side === 'home' ? 'simHomeBenchCount' : 'simAwayBenchCount');
            const pids = simState[side].bench;
            count.textContent = pids.length;
            if (pids.length === 0) {
                zone.innerHTML = '<span class="sim-bench-hint">Drag players here</span>';
            } else {
                zone.innerHTML = pids.map(pid => simBuildCard(pid, side)).join('');
            }
        }

        function simRenderLocker(side) {
            const zone = document.getElementById(side === 'home' ? 'simHomeLockerZone' : 'simAwayLockerZone');
            const count = document.getElementById(side === 'home' ? 'simHomeLockerCount' : 'simAwayLockerCount');
            const pids = simState[side].locker;
            count.textContent = pids.length;
            zone.innerHTML = pids.map(pid => simBuildCard(pid, side)).join('');
        }

        // ─── DRAG AND DROP ───
        function simDragStart(e) {
            const card = e.target.closest('.sim-card');
            if (!card) return;
            simDragPid = parseInt(card.dataset.pid);
            simDragSrcSide = card.dataset.side;
            // Determine source zone
            if (card.closest('.sim-pos-slot')) simDragSrcZone = 'court';
            else if (card.closest('.sim-bench-zone')) simDragSrcZone = 'bench';
            else simDragSrcZone = 'locker';
            card.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', simDragPid);
        }
        function simDragEnd(e) {
            document.querySelectorAll('.sim-card.dragging').forEach(c => c.classList.remove('dragging'));
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            simDragPid = null;
        }
        function simAllowDrop(e) {
            e.preventDefault();
            const target = e.target.closest('.sim-pos-slot, .sim-bench-zone, .sim-locker-zone');
            if (target) target.classList.add('drag-over');
        }
        function simDrop(e, side, zone) {
            e.preventDefault();
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            if (!simDragPid) return;
            const pid = simDragPid;
            const srcSide = simDragSrcSide;
            const srcZone = simDragSrcZone;

            // Can only move within same team
            if (srcSide !== side) return;

            // Remove from source
            ['court','bench','locker'].forEach(z => {
                const idx = simState[side][z].indexOf(pid);
                if (idx >= 0) simState[side][z].splice(idx, 1);
            });

            // Add to destination
            if (zone === 'court') {
                if (simState[side].court.length >= 5) {
                    // Court full — swap: bump last court player to bench
                    const bumped = simState[side].court.pop();
                    simState[side].bench.push(bumped);
                }
                // If dropping on a position slot, try to place at that position
                const slot = e.target.closest('.sim-pos-slot');
                if (slot && slot.dataset.pos) {
                    // Remove existing player at that position
                    const existing = simState[side].court.find(id => {
                        const pl = simGetPlayerById(id);
                        return pl && (pl.pos || 'SF') === slot.dataset.pos;
                    });
                    if (existing && existing !== pid) {
                        simState[side].court = simState[side].court.filter(id => id !== existing);
                        simState[side].bench.push(existing);
                    }
                }
                simState[side].court.push(pid);
                if (!simPlayerMinutes[pid] || simPlayerMinutes[pid] === 0) simPlayerMinutes[pid] = 28;
            } else if (zone === 'bench') {
                simState[side].bench.push(pid);
                if (!simPlayerMinutes[pid] || simPlayerMinutes[pid] === 0) simPlayerMinutes[pid] = 16;
            } else {
                simState[side].locker.push(pid);
                simPlayerMinutes[pid] = 0;
            }

            simRenderAll(side);
            simRecalc();
            simCheckReady();
        }

        // ─── TOUCH DRAG SUPPORT ───
        let simTouchClone = null;
        let simTouchPid = null;
        let simTouchSide = null;
        let simTouchSrcZone = null;
        function simTouchStart(e) {
            const card = e.target.closest('.sim-card');
            if (!card) return;
            // Don't intercept slider touches
            if (e.target.tagName === 'INPUT') return;
            simTouchPid = parseInt(card.dataset.pid);
            simTouchSide = card.dataset.side;
            if (card.closest('.sim-pos-slot')) simTouchSrcZone = 'court';
            else if (card.closest('.sim-bench-zone')) simTouchSrcZone = 'bench';
            else simTouchSrcZone = 'locker';
            const rect = card.getBoundingClientRect();
            simTouchClone = card.cloneNode(true);
            simTouchClone.style.cssText = 'position:fixed;z-index:9999;pointer-events:none;opacity:0.8;width:'+rect.width+'px;';
            simTouchClone.style.left = rect.left + 'px';
            simTouchClone.style.top = rect.top + 'px';
            document.body.appendChild(simTouchClone);
            card.classList.add('dragging');
        }
        function simTouchMove(e) {
            if (!simTouchClone) return;
            e.preventDefault();
            const t = e.touches[0];
            simTouchClone.style.left = (t.clientX - 40) + 'px';
            simTouchClone.style.top = (t.clientY - 40) + 'px';
        }
        function simTouchEnd(e) {
            if (!simTouchClone) return;
            const t = e.changedTouches[0];
            simTouchClone.remove();
            simTouchClone = null;
            document.querySelectorAll('.sim-card.dragging').forEach(c => c.classList.remove('dragging'));
            // Find drop target
            const el = document.elementFromPoint(t.clientX, t.clientY);
            if (!el) return;
            const slot = el.closest('.sim-pos-slot');
            const bench = el.closest('.sim-bench-zone');
            const locker = el.closest('.sim-locker-zone');
            let zone = null;
            let side = simTouchSide;
            if (slot) { zone = 'court'; side = slot.dataset.side || side; }
            else if (bench) zone = 'bench';
            else if (locker) zone = 'locker';
            if (zone && side === simTouchSide) {
                simDragPid = simTouchPid;
                simDragSrcSide = simTouchSide;
                simDragSrcZone = simTouchSrcZone;
                simDrop({preventDefault:()=>{}, target: el}, side, zone);
            }
        }

        // ─── MOJI COMPUTATION (formula-accurate) ───
        function simComputeMoji(side) {
            const abbr = simState[side].team;
            if (!abbr || !SIM_DATA.rosters[abbr]) return 0;
            const roster = SIM_DATA.rosters[abbr];
            const courtPids = simState[side].court;
            const benchPids = simState[side].bench;
            const lockerPids = simState[side].locker;
            const activePids = [...courtPids, ...benchPids];
            if (activePids.length === 0) return 0;

            // Build player map
            const pmap = {};
            roster.forEach(p => { pmap[p.id] = p; });

            // Compute total usage of active players & DNP players
            let activeUsgTotal = 0;
            let dnpUsgTotal = 0;
            activePids.forEach(pid => { activeUsgTotal += (pmap[pid]||{}).usg || 20; });
            lockerPids.forEach(pid => { dnpUsgTotal += (pmap[pid]||{}).usg || 20; });

            // Redistribute usage from DNP players
            activePids.forEach(pid => {
                const p = pmap[pid];
                if (!p) return;
                const baseMojo = p.mojo;
                const baseUsg = p.usg || 20;
                const playerMpg = simPlayerMinutes[pid] || Math.round(p.mpg);
                const seasonMpg = p.mpg || 20;
                const minRatio = playerMpg / Math.max(seasonMpg, 1);

                // Extra usage from DNP redistribution
                let extraUsg = 0;
                if (dnpUsgTotal > 0 && activeUsgTotal > 0) {
                    const arch = p.archetype || '';
                    const sameArchFrac = 0.6;
                    const samePosTotal = activePids.filter(id => pmap[id] && pmap[id].pos === p.pos).length;
                    const share = baseUsg / activeUsgTotal;
                    extraUsg = dnpUsgTotal * share * 0.5;
                }
                const newUsg = baseUsg + extraUsg;
                const usgPct = (newUsg - baseUsg) / Math.max(baseUsg, 1) * 100;

                // Decay per 1% extra usage
                const isDefArch = (p.archetype || '').toLowerCase().includes('def') ||
                                  (p.archetype || '').toLowerCase().includes('rim') ||
                                  (p.archetype || '').toLowerCase().includes('anchor');
                const decayRate = isDefArch ? 0.985 : 0.995;
                let usgFactor = Math.pow(decayRate, Math.max(0, usgPct));

                // Minutes factor
                let minFactor = 1.0;
                if (minRatio > 1.5) {
                    minFactor = 0.96; // fatigue
                } else if (minRatio >= 0.5 && minRatio <= 0.8 && !isDefArch) {
                    minFactor = 1.01; // rhythm boost for bench promoted
                }

                const adjMojo = baseMojo * usgFactor * minFactor;
                simAdjustedMojo[pid] = Math.round(Math.max(33, Math.min(99, adjMojo)));
            });

            // DNP players get 0
            lockerPids.forEach(pid => { simAdjustedMojo[pid] = 0; });

            // MOJI = minutes-weighted avg of adjusted MOJO
            let totalWeighted = 0;
            let totalMin = 0;
            activePids.forEach(pid => {
                const mpg = simPlayerMinutes[pid] || (pmap[pid] ? Math.round(pmap[pid].mpg) : 20);
                totalWeighted += (simAdjustedMojo[pid] || 0) * mpg;
                totalMin += mpg;
            });
            return totalMin > 0 ? totalWeighted / totalMin : 0;
        }

        function simRecalc() {
            ['home','away'].forEach(side => {
                const moji = simComputeMoji(side);
                const badge = document.getElementById(side === 'home' ? 'simHomeMojiBadge' : 'simAwayMojiBadge');
                // Preserve the tooltip children — only update the text node
                const textVal = 'MOJI ' + (moji > 0 ? moji.toFixed(1) : '—');
                const firstText = badge.childNodes[0];
                if (firstText && firstText.nodeType === 3) { firstText.textContent = textVal; }
                else { badge.insertBefore(document.createTextNode(textVal), badge.firstChild); }
            });
            // Update card MOJO badges to show adjusted values
            document.querySelectorAll('.sim-card').forEach(card => {
                const pid = parseInt(card.dataset.pid);
                if (simAdjustedMojo[pid] !== undefined && simAdjustedMojo[pid] > 0) {
                    const mojoEl = card.querySelector('.sim-card-mojo');
                    if (mojoEl) mojoEl.textContent = simAdjustedMojo[pid];
                    // Update tier
                    card.className = card.className.replace(/tier-\w+/, simCardTier(simAdjustedMojo[pid]));
                }
            });
            simCheckReady();
        }

        function simCheckReady() {
            const btn = document.getElementById('simRunBtn');
            const info = document.getElementById('simActionInfo');
            const hC = simState.home.court.length;
            const aC = simState.away.court.length;
            if (hC === 5 && aC === 5) {
                btn.disabled = false;
                info.textContent = 'Ready to simulate!';
            } else {
                btn.disabled = true;
                const need = [];
                if (hC < 5) need.push('Home: ' + hC + '/5');
                if (aC < 5) need.push('Away: ' + aC + '/5');
                info.textContent = need.join(' | ');
            }
        }

        // ─── SIMULATION ENGINE ───
        function gaussRand() {
            let u = 0, v = 0;
            while (u === 0) u = Math.random();
            while (v === 0) v = Math.random();
            return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
        }
        function poissonRand(lambda) {
            let L = Math.exp(-lambda), k = 0, p = 1;
            do { k++; p *= Math.random(); } while (p > L);
            return k - 1;
        }

        function weightedPick(items, weights) {
            let total = weights.reduce((a, b) => a + b, 0);
            let r = Math.random() * total;
            for (let i = 0; i < items.length; i++) {
                r -= weights[i];
                if (r <= 0) return items[i];
            }
            return items[items.length - 1];
        }

        function shuffleArray(arr) {
            for (let i = arr.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [arr[i], arr[j]] = [arr[j], arr[i]];
            }
        }

        // Shot chart zone definitions (viewBox 0 0 400 380)
        const SHOT_ZONES = {
            rim:          { cx: 200, cy: 305, r: 20 },
            paint_left:   { cx: 160, cy: 280, r: 18 },
            paint_right:  { cx: 240, cy: 280, r: 18 },
            paint_mid:    { cx: 200, cy: 265, r: 15 },
            mid_left:     { cx: 100, cy: 260, r: 22 },
            mid_right:    { cx: 300, cy: 260, r: 22 },
            elbow_left:   { cx: 120, cy: 210, r: 20 },
            elbow_right:  { cx: 280, cy: 210, r: 20 },
            mid_top:      { cx: 200, cy: 195, r: 18 },
            corner_left:  { cx: 35,  cy: 295, r: 12 },
            corner_right: { cx: 365, cy: 295, r: 12 },
            wing_left:    { cx: 55,  cy: 200, r: 18 },
            wing_right:   { cx: 345, cy: 200, r: 18 },
            top_key:      { cx: 200, cy: 120, r: 22 },
        };

        const PAINT_ZONES = ['rim','paint_left','paint_right','paint_mid'];
        const PAINT_WEIGHTS = [0.40, 0.20, 0.20, 0.20];
        const MID_ZONES = ['mid_left','mid_right','elbow_left','elbow_right','mid_top'];
        const MID_WEIGHTS = [0.18, 0.18, 0.22, 0.22, 0.20];
        const THREE_ZONES = ['corner_left','corner_right','wing_left','wing_right','top_key'];

        const ARCH_PAINT_RATIO = {
            "Scoring Guard": 0.55, "Defensive Specialist": 0.60, "Floor General": 0.50,
            "Combo Guard": 0.50, "Playmaking Guard": 0.45, "Two-Way Wing": 0.50,
            "Slasher": 0.80, "Sharpshooter": 0.30, "3-and-D Wing": 0.45,
            "Point Forward": 0.50, "Stretch Forward": 0.35, "Athletic Wing": 0.60,
            "Stretch Big": 0.55, "Traditional PF": 0.75, "Small-Ball 4": 0.50,
            "Two-Way Forward": 0.55, "Rim Protector": 0.90, "Stretch 5": 0.50,
            "Traditional Center": 0.90, "Versatile Big": 0.55, "Unclassified": 0.55,
        };

        const ARCH_3PT = {
            "3-and-D Wing":         [0.25,0.25,0.18,0.18,0.14],
            "Stretch Forward":      [0.22,0.22,0.20,0.20,0.16],
            "Stretch Big":          [0.20,0.20,0.20,0.20,0.20],
            "Stretch 5":            [0.22,0.22,0.18,0.18,0.20],
            "Sharpshooter":         [0.15,0.15,0.25,0.25,0.20],
            "Scoring Guard":        [0.12,0.12,0.22,0.22,0.32],
            "Playmaking Guard":     [0.10,0.10,0.22,0.22,0.36],
            "Floor General":        [0.12,0.12,0.22,0.22,0.32],
            "Combo Guard":          [0.15,0.15,0.22,0.22,0.26],
            "Two-Way Wing":         [0.18,0.18,0.22,0.22,0.20],
            "Point Forward":        [0.15,0.15,0.22,0.22,0.26],
            "Athletic Wing":        [0.18,0.18,0.22,0.22,0.20],
            "Slasher":              [0.25,0.25,0.20,0.20,0.10],
            "Defensive Specialist": [0.28,0.28,0.18,0.18,0.08],
            "Traditional PF":       [0.25,0.25,0.20,0.20,0.10],
            "Small-Ball 4":         [0.18,0.18,0.22,0.22,0.20],
            "Two-Way Forward":      [0.20,0.20,0.20,0.20,0.20],
            "Rim Protector":        [0.30,0.30,0.15,0.15,0.10],
            "Traditional Center":   [0.30,0.30,0.15,0.15,0.10],
            "Versatile Big":        [0.20,0.20,0.20,0.20,0.20],
            "Unclassified":         [0.20,0.20,0.20,0.20,0.20],
        };

        function generatePlayerShots(fgm, fga, tpm, tpa, archetype) {
            const arch = archetype || 'Unclassified';
            const shots = [];
            // 3-point shots
            const threeW = ARCH_3PT[arch] || ARCH_3PT['Unclassified'];
            for (let s = 0; s < tpa; s++) {
                const zn = SHOT_ZONES[weightedPick(THREE_ZONES, threeW)];
                shots.push({
                    x: zn.cx + (Math.random()-0.5) * zn.r * 2,
                    y: zn.cy + (Math.random()-0.5) * zn.r * 2,
                    made: s < tpm, is3: true
                });
            }
            shuffleArray(shots);
            // 2-point shots
            const twoPtA = fga - tpa;
            const twoPtM = fgm - tpm;
            const paintRatio = ARCH_PAINT_RATIO[arch] || 0.55;
            const paintCount = Math.round(twoPtA * paintRatio);
            const midCount = twoPtA - paintCount;
            const twoShots = [];
            for (let s = 0; s < paintCount; s++) {
                const zn = SHOT_ZONES[weightedPick(PAINT_ZONES, PAINT_WEIGHTS)];
                twoShots.push({
                    x: zn.cx + (Math.random()-0.5) * zn.r * 2,
                    y: zn.cy + (Math.random()-0.5) * zn.r * 2,
                    made: false, is3: false
                });
            }
            for (let s = 0; s < midCount; s++) {
                const zn = SHOT_ZONES[weightedPick(MID_ZONES, MID_WEIGHTS)];
                twoShots.push({
                    x: zn.cx + (Math.random()-0.5) * zn.r * 2,
                    y: zn.cy + (Math.random()-0.5) * zn.r * 2,
                    made: false, is3: false
                });
            }
            shuffleArray(twoShots);
            for (let s = 0; s < Math.min(twoPtM, twoShots.length); s++) {
                twoShots[s].made = true;
            }
            shuffleArray(twoShots);
            return [...shots, ...twoShots];
        }

        function buildShotChartSVG(shots, teamColor) {
            const ls = 'rgba(255,255,255,0.12)', lw = '1.5';
            let svg = '<svg viewBox="0 0 400 380" style="width:100%;max-width:400px;display:block;margin:0 auto">';
            svg += '<rect x="0" y="0" width="400" height="380" fill="#1a1a1a" rx="8"/>';
            // Baseline
            svg += '<line x1="0" y1="340" x2="400" y2="340" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            // Paint
            svg += '<rect x="130" y="200" width="140" height="140" fill="none" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            // FT circle
            svg += '<circle cx="200" cy="200" r="60" fill="none" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            // Restricted area
            svg += '<path d="M 160 340 A 40 40 0 0 1 240 340" fill="none" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            // 3-point line
            svg += '<line x1="30" y1="340" x2="30" y2="200" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            svg += '<line x1="370" y1="340" x2="370" y2="200" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            svg += '<path d="M 30 200 Q 30 60 200 20 Q 370 60 370 200" fill="none" stroke="'+ls+'" stroke-width="'+lw+'"/>';
            // Backboard + rim
            svg += '<line x1="185" y1="335" x2="215" y2="335" stroke="rgba(255,255,255,0.25)" stroke-width="2"/>';
            svg += '<circle cx="200" cy="328" r="7" fill="none" stroke="rgba(255,255,255,0.25)" stroke-width="1.5"/>';
            // Shot dots
            shots.forEach(function(s) {
                const x = Math.max(5, Math.min(395, s.x));
                const y = Math.max(15, Math.min(338, s.y));
                if (s.made) {
                    svg += '<circle cx="'+x.toFixed(1)+'" cy="'+y.toFixed(1)+'" r="5" fill="'+(teamColor||'#00FF55')+'" opacity="0.85"/>';
                } else {
                    svg += '<line x1="'+(x-3.5).toFixed(1)+'" y1="'+(y-3.5).toFixed(1)+'" x2="'+(x+3.5).toFixed(1)+'" y2="'+(y+3.5).toFixed(1)+'" stroke="#FF3333" stroke-width="1.8" opacity="0.7"/>';
                    svg += '<line x1="'+(x+3.5).toFixed(1)+'" y1="'+(y-3.5).toFixed(1)+'" x2="'+(x-3.5).toFixed(1)+'" y2="'+(y+3.5).toFixed(1)+'" stroke="#FF3333" stroke-width="1.8" opacity="0.7"/>';
                }
            });
            // Legend
            svg += '<circle cx="15" cy="365" r="4" fill="'+(teamColor||'#00FF55')+'"/>';
            svg += '<text x="24" y="368" fill="rgba(255,255,255,0.6)" font-size="10" font-family="JetBrains Mono,monospace">MAKE</text>';
            svg += '<text x="80" y="368" fill="#FF3333" font-size="12" font-family="JetBrains Mono,monospace" font-weight="700">x</text>';
            svg += '<text x="92" y="368" fill="rgba(255,255,255,0.6)" font-size="10" font-family="JetBrains Mono,monospace">MISS</text>';
            svg += '</svg>';
            return svg;
        }

        let simShotData = {};
        let currentShotChartKey = null;

        function toggleShotChart(key, teamColor) {
            const container = document.getElementById('simShotChart');
            if (currentShotChartKey === key) {
                container.style.display = 'none';
                container.innerHTML = '';
                currentShotChartKey = null;
                document.querySelectorAll('.sim-box-clickable.active-chart').forEach(el => el.classList.remove('active-chart'));
                return;
            }
            currentShotChartKey = key;
            const p = simShotData[key];
            if (!p || !p.shots || p.shots.length === 0) {
                container.innerHTML = '<div class="sc-wrapper" style="justify-content:center;padding:24px;color:rgba(0,0,0,0.4);font-family:var(--font-mono)">NO SHOT DATA</div>';
                container.style.display = 'block';
                return;
            }
            document.querySelectorAll('.sim-box-clickable.active-chart').forEach(el => el.classList.remove('active-chart'));
            document.querySelectorAll('.sim-box-clickable').forEach(el => {
                if (el.querySelector('td') && el.querySelector('td').textContent === p.name) el.classList.add('active-chart');
            });
            const fgPct = p.fga > 0 ? (p.fgm/p.fga*100).toFixed(1) : '0.0';
            const tpPct = p.tpa > 0 ? (p.tpm/p.tpa*100).toFixed(1) : '0.0';
            const ftPct = p.fta > 0 ? (p.ftm/p.fta*100).toFixed(1) : '0.0';
            const efg = p.fga > 0 ? ((p.fgm + 0.5*p.tpm)/p.fga*100).toFixed(1) : '0.0';
            const ts = (p.fga + 0.44*p.fta) > 0 ? (p.pts/(2*(p.fga+0.44*p.fta))*100).toFixed(1) : '0.0';
            const paint = p.shots.filter(s => !s.is3 && s.y > 240).length;
            const paintM = p.shots.filter(s => !s.is3 && s.y > 240 && s.made).length;
            const mid = p.shots.filter(s => !s.is3 && s.y <= 240).length;
            const midM = p.shots.filter(s => !s.is3 && s.y <= 240 && s.made).length;
            const three = p.shots.filter(s => s.is3).length;
            const threeM = p.shots.filter(s => s.is3 && s.made).length;
            const chartSvg = buildShotChartSVG(p.shots, teamColor);
            const statsHtml = '<div class="sc-stats">'
                + '<div class="sc-player-name">' + p.name + '</div>'
                + '<div class="sc-archetype">' + (p.archetype||'') + '</div>'
                + '<div class="sc-stat-grid">'
                + '<div class="sc-stat"><span class="sc-stat-val">' + p.pts + '</span><span class="sc-stat-label">PTS</span></div>'
                + '<div class="sc-stat"><span class="sc-stat-val">' + fgPct + '%</span><span class="sc-stat-label">FG%</span></div>'
                + '<div class="sc-stat"><span class="sc-stat-val">' + tpPct + '%</span><span class="sc-stat-label">3P%</span></div>'
                + '<div class="sc-stat"><span class="sc-stat-val">' + ftPct + '%</span><span class="sc-stat-label">FT%</span></div>'
                + '<div class="sc-stat"><span class="sc-stat-val">' + efg + '%</span><span class="sc-stat-label">eFG%</span></div>'
                + '<div class="sc-stat"><span class="sc-stat-val">' + ts + '%</span><span class="sc-stat-label">TS%</span></div>'
                + '</div>'
                + '<div class="sc-zone-breakdown">'
                + '<div class="sc-zone-row"><span>PAINT</span><span>' + paintM + '/' + paint + '</span></div>'
                + '<div class="sc-zone-row"><span>MID-RANGE</span><span>' + midM + '/' + mid + '</span></div>'
                + '<div class="sc-zone-row"><span>3-POINT</span><span>' + threeM + '/' + three + '</span></div>'
                + '</div></div>';
            container.innerHTML = '<div class="sc-wrapper">' + chartSvg + statsHtml + '</div>';
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        function simComputePairSynergy(side) {
            const pids = simState[side].court;
            if (pids.length < 2) return 50;
            const pairs = SIM_DATA.pairs || {};
            let total = 0, count = 0;
            for (let i = 0; i < pids.length; i++) {
                for (let j = i + 1; j < pids.length; j++) {
                    const key1 = pids[i] + '-' + pids[j];
                    const key2 = pids[j] + '-' + pids[i];
                    const syn = pairs[key1] || pairs[key2];
                    if (syn && syn.syn !== undefined) { total += syn.syn; count++; }
                }
            }
            return count > 0 ? total / count : 50;
        }

        function simRunGame() {
            if (simState.home.court.length !== 5 || simState.away.court.length !== 5) return;
            const hAbbr = simState.home.team;
            const aAbbr = simState.away.team;
            const hStats = SIM_DATA.team_stats[hAbbr] || {};
            const aStats = SIM_DATA.team_stats[aAbbr] || {};

            // Compute MOJIs
            const hMoji = simComputeMoji('home');
            const aMoji = simComputeMoji('away');
            const mojiDiff = hMoji - aMoji;

            // Pair synergy
            const hSyn = simComputePairSynergy('home');
            const aSyn = simComputePairSynergy('away');
            const synDiff = hSyn - aSyn;

            // NRtg
            const hNrtg = hStats.nrtg || 0;
            const aNrtg = aStats.nrtg || 0;
            const nrtgDiff = hNrtg - aNrtg;

            // HCA
            const venue = document.getElementById('simVenue').value;
            let hca = 0;
            if (venue === 'home') {
                hca = (SIM_DATA.team_hca && SIM_DATA.team_hca[hAbbr]) ? SIM_DATA.team_hca[hAbbr] : 1.8;
            }

            // B2B
            const hB2B = document.getElementById('simHomeB2B').checked ? -2.0 : 0;
            const aB2B = document.getElementById('simAwayB2B').checked ? -2.5 : 0;

            // Power rating
            const rawPower = 0.45 * mojiDiff + 0.35 * nrtgDiff + 0.20 * synDiff;
            const spread = -(rawPower + hca + hB2B - aB2B);

            // Expected points
            const pace = ((hStats.pace || 100) * (aStats.pace || 100)) / 99.87;
            const hOrtg = (hStats.ortg || 111.7) + mojiDiff * 0.3 + hca/2 + hB2B;
            const aOrtg = (aStats.ortg || 111.7) - mojiDiff * 0.3 - hca/2 + aB2B;
            const hDrtg = hStats.drtg || 111.7;
            const aDrtg = aStats.drtg || 111.7;
            const hExpected = ((hOrtg + aDrtg) / 2) * (pace / 100);
            const aExpected = ((aOrtg + hDrtg) / 2) * (pace / 100);

            // Generate quarters
            const quarters = generateQuarters(hExpected, aExpected, pace);

            // Box scores
            const hBox = generateBoxScore('home', quarters.hTotal);
            const aBox = generateBoxScore('away', quarters.aTotal);

            // Win probability (simple logistic)
            const diff = quarters.hTotal - quarters.aTotal;
            const winProb = 1 / (1 + Math.exp(-diff * 0.15));

            renderSimResults(quarters, hBox, aBox, winProb);
        }

        function generateQuarters(hTotal, aTotal, pace) {
            const hq = [], aq = [];
            let hSum = 0, aSum = 0;
            for (let q = 0; q < 3; q++) {
                const hPts = Math.round(hTotal / 4 + gaussRand() * 4.5);
                const aPts = Math.round(aTotal / 4 + gaussRand() * 4.5);
                hq.push(Math.max(15, hPts));
                aq.push(Math.max(15, aPts));
                hSum += hq[q]; aSum += aq[q];
            }
            hq.push(Math.max(15, Math.round(hTotal - hSum + gaussRand() * 2)));
            aq.push(Math.max(15, Math.round(aTotal - aSum + gaussRand() * 2)));
            const hFinal = hq.reduce((a,b) => a+b, 0);
            const aFinal = aq.reduce((a,b) => a+b, 0);
            return { hq, aq, hTotal: hFinal, aTotal: aFinal };
        }

        function generateBoxScore(side, teamTotal) {
            const abbr = simState[side].team;
            const roster = SIM_DATA.rosters[abbr] || [];
            const pmap = {};
            roster.forEach(p => { pmap[p.id] = p; });
            const courtPids = simState[side].court;
            const benchPids = simState[side].bench;
            const activePids = [...courtPids, ...benchPids];
            const lines = [];

            // Total usage for active players
            let totalUsgMin = 0;
            activePids.forEach(pid => {
                const p = pmap[pid];
                if (!p) return;
                const min = simPlayerMinutes[pid] || Math.round(p.mpg);
                totalUsgMin += (p.usg || 20) * min;
            });

            // --- Pass 1: allocate raw points proportional to usage, then reconcile to teamTotal ---
            let ptsRemaining = teamTotal;
            const rawPts = [];
            const activeData = [];

            activePids.forEach((pid) => {
                const p = pmap[pid];
                if (!p) return;
                const min = simPlayerMinutes[pid] || Math.round(p.mpg);
                if (min <= 0) return;
                const usgMin = (p.usg || 20) * min;
                const share = totalUsgMin > 0 ? usgMin / totalUsgMin : 1 / activePids.length;
                let pts = Math.round(teamTotal * share + gaussRand() * 2);
                pts = Math.max(0, pts);
                rawPts.push(pts);
                activeData.push({ pid, p, min, share });
            });

            // Reconcile: adjust so individual points sum exactly to teamTotal
            let rawSum = rawPts.reduce((a, b) => a + b, 0);
            let diff = teamTotal - rawSum;
            // Distribute remainder to highest-usage players first
            if (diff !== 0) {
                const sorted = activeData.map((d, i) => ({ i, share: d.share }))
                    .sort((a, b) => b.share - a.share);
                const step = diff > 0 ? 1 : -1;
                let idx = 0;
                while (diff !== 0) {
                    const target = sorted[idx % sorted.length].i;
                    if (step < 0 && rawPts[target] <= 0) { idx++; continue; }
                    rawPts[target] += step;
                    diff -= step;
                    idx++;
                }
            }

            // --- Pass 2: generate box score lines from reconciled points ---
            const playerLines = [];

            activeData.forEach((d, i) => {
                const { pid, p, min } = d;
                const pts = rawPts[i];
                const minRatio = min / 36;
                const reb = Math.max(0, poissonRand((p.reb || 3) * minRatio));
                const ast = Math.max(0, poissonRand((p.ast || 2) * minRatio));
                const stl = Math.max(0, poissonRand((p.stl || 0.5) * minRatio));
                const blk = Math.max(0, poissonRand((p.blk || 0.3) * minRatio));

                // Derive shooting splits: FT first (credit those points), then FG from remainder
                const fta = Math.max(0, poissonRand(pts * 0.22));
                const ftPct = 0.7 + Math.random() * 0.15;
                const ftm = Math.min(fta, Math.round(fta * ftPct));
                const ptsFromFt = ftm;
                const ptsFromFg = Math.max(0, pts - ptsFromFt);

                // FGA from remaining points using eFG% (accounts for 3-pt bonus)
                const efg = 0.48 + Math.random() * 0.12;  // ~48-60% eFG
                const fga = ptsFromFg > 0 ? Math.max(1, Math.round(ptsFromFg / (efg * 2))) : 0;
                const tpa = Math.max(0, Math.round(fga * (0.30 + Math.random() * 0.15)));
                const tpm = Math.min(tpa, Math.round(tpa * (0.28 + Math.random() * 0.15)));
                const fgPtsFrom3 = tpm * 3;
                const fgPtsFrom2 = Math.max(0, ptsFromFg - fgPtsFrom3);
                const fg2m = Math.round(fgPtsFrom2 / 2);
                const fgm = Math.min(fga, fg2m + tpm);

                const plusMinus = Math.round(gaussRand() * 8);

                // Generate shot location data for shot chart
                const playerShots = generatePlayerShots(fgm, fga, tpm, tpa, p.archetype);

                playerLines.push({
                    name: p.name, min, pts, reb, ast, stl, blk,
                    fgm, fga, tpm, tpa, ftm, fta, plusMinus,
                    isStarter: courtPids.includes(pid),
                    mojo: simAdjustedMojo[pid] || p.mojo,
                    archetype: p.archetype || 'Unclassified',
                    shots: playerShots
                });
            });

            return playerLines;
        }

        function renderSimResults(quarters, hBox, aBox, winProb) {
            const hAbbr = simState.home.team;
            const aAbbr = simState.away.team;
            const hCol = SIM_DATA.team_colors[hAbbr] || '#00FF55';
            const aCol = SIM_DATA.team_colors[aAbbr] || '#CE1141';
            const hWin = quarters.hTotal > quarters.aTotal;

            // Score display in center column
            const scoreEl = document.getElementById('simScoreDisplay');
            const hHalf = quarters.hq[0] + quarters.hq[1];
            const aHalf = quarters.aq[0] + quarters.aq[1];
            scoreEl.innerHTML =
                '<div class="sim-score-line">' +
                '<span class="sim-score-team">' + hAbbr + '</span>' +
                '<span class="sim-score-qtrs">' + quarters.hq.join(' ') + '</span>' +
                '<span class="sim-score-final ' + (hWin ? 'sim-score-winner' : '') + '">' + quarters.hTotal + '</span>' +
                '</div>' +
                '<div class="sim-score-line">' +
                '<span class="sim-score-team">' + aAbbr + '</span>' +
                '<span class="sim-score-qtrs">' + quarters.aq.join(' ') + '</span>' +
                '<span class="sim-score-final ' + (!hWin ? 'sim-score-winner' : '') + '">' + quarters.aTotal + '</span>' +
                '</div>';

            // Win probability bar
            const probBar = document.getElementById('simWinProbBar');
            const hPct = Math.round(winProb * 100);
            const aPct = 100 - hPct;
            probBar.innerHTML =
                '<div class="sim-winprob-home" style="width:' + hPct + '%;background:' + hCol + '">' + hPct + '%</div>' +
                '<div class="sim-winprob-away" style="width:' + aPct + '%;background:' + aCol + '">' + aPct + '%</div>';

            document.getElementById('simCenterResults').style.display = 'block';

            // Box scores (full width below)
            const boxEl = document.getElementById('simBoxScores');
            boxEl.style.display = 'grid';
            boxEl.innerHTML = renderBoxTable(hAbbr, hBox, hCol) + renderBoxTable(aAbbr, aBox, aCol);

            boxEl.scrollIntoView({behavior:'smooth'});
        }

        function renderBoxTable(abbr, players, color) {
            const logo = simGetTeamLogo(abbr);
            let html = '<div class="sim-box-team">' +
                '<div class="sim-box-header" style="background:'+color+';color:#fff">' +
                '<img src="'+logo+'" style="width:24px;height:24px">' + abbr + '</div>' +
                '<table class="sim-box-table"><thead><tr>' +
                '<th>NAME</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FG</th><th>3PT</th><th>FT</th><th>+/-</th>' +
                '</tr></thead><tbody>';
            let tPts=0,tReb=0,tAst=0,tStl=0,tBlk=0,tMin=0,tFgm=0,tFga=0,tTpm=0,tTpa=0,tFtm=0,tFta=0;
            players.forEach((p, idx) => {
                const key = (p.name + '|' + abbr).replace(/'/g, '');
                simShotData[p.name + '|' + abbr] = p;
                const cls = p.isStarter ? 'sim-box-starter' : 'sim-box-bench';
                html += '<tr class="'+cls+' sim-box-clickable" data-shot-key="'+key+'" data-shot-color="'+color+'">' +
                    '<td>'+p.name+'</td><td>'+p.min+'</td><td>'+p.pts+'</td>' +
                    '<td>'+p.reb+'</td><td>'+p.ast+'</td><td>'+p.stl+'</td><td>'+p.blk+'</td>' +
                    '<td>'+p.fgm+'-'+p.fga+'</td><td>'+p.tpm+'-'+p.tpa+'</td><td>'+p.ftm+'-'+p.fta+'</td>' +
                    '<td>'+(p.plusMinus>=0?'+':'')+p.plusMinus+'</td></tr>';
                tPts+=p.pts; tReb+=p.reb; tAst+=p.ast; tStl+=p.stl; tBlk+=p.blk; tMin+=p.min;
                tFgm+=p.fgm; tFga+=p.fga; tTpm+=p.tpm; tTpa+=p.tpa; tFtm+=p.ftm; tFta+=p.fta;
            });
            html += '<tr class="sim-box-total"><td>TOTAL</td><td>'+tMin+'</td><td>'+tPts+'</td>' +
                '<td>'+tReb+'</td><td>'+tAst+'</td><td>'+tStl+'</td><td>'+tBlk+'</td>' +
                '<td>'+tFgm+'-'+tFga+'</td><td>'+tTpm+'-'+tTpa+'</td><td>'+tFtm+'-'+tFta+'</td><td></td></tr>';
            html += '</tbody></table></div>';
            return html;
        }

        // Delegated click for box score rows (avoid inline onclick with quote issues)
        document.getElementById('simBoxScores').addEventListener('click', function(e) {
            const row = e.target.closest('.sim-box-clickable');
            if (row) {
                const key = row.dataset.shotKey;
                const color = row.dataset.shotColor;
                if (key && color) toggleShotChart(key, color);
            }
        });

        function simResim() {
            document.getElementById('simCenterResults').style.display = 'none';
            document.getElementById('simBoxScores').style.display = 'none';
            document.getElementById('simShotChart').style.display = 'none';
            document.getElementById('simShotChart').innerHTML = '';
            currentShotChartKey = null;
            simShotData = {};
            document.getElementById('simThreeCol').scrollIntoView({behavior:'smooth'});
        }