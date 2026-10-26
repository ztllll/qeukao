package main

import (
	"math/rand"
	"strings"
	"testing"
)

func TestDefaultMessageKeepsTheBigFontAndTheContractSize(t *testing.T) {
	for _, scale := range []int32{100, 125, 150} {
		h, px := fitNotice("请点击确定填写缺考信息", 819, 458, 768, scale)
		if px != 40*scale/100 || h != 458 {
			t.Fatalf("scale %d: default text must keep the big font at the contract height, got px=%d height=%d", scale, px, h)
		}
	}
}

// 与服务端 qk_agents.display_lines / 管理端 messageDisplayLines 共用的向量：三边必须给出同一个行数。
// 改这张表时要同时改 tests/test_agents_http.py 里的同名向量。
var displayLineVectors = []struct {
	text  string
	lines int
}{
	{"", 1}, {"请点击确定填写缺考信息", 1}, {strings.Repeat("字", 30), 1}, {strings.Repeat("字", 31), 2},
	{strings.Repeat("字", 200), 7}, {"a\nb\nc", 3}, {"a\n\nb", 3}, {strings.Repeat("字", 186) + strings.Repeat("\n字", 7), 14},
	{strings.Repeat("字", 30) + "\n" + strings.Repeat("字", 31), 3},
	// emoji 与 U+2600–27BF 符号按 2 个字符宽计（它们实际占 ~2em）：15 个一行，16 个就折成两行
	{strings.Repeat("😀", 15), 1}, {strings.Repeat("😀", 16), 2}, {strings.Repeat("😀", 21), 2}, {strings.Repeat("☀", 16), 2},
	// 未知一律保守：除 ASCII、拉丁字母(<U+0250)、常用标点(U+2000-206F)、CJK 以外的字符都按 2 计（数学粗体、箭头、西里尔、希腊…）
	{strings.Repeat("é", 30), 1}, {strings.Repeat("“", 30), 1}, {strings.Repeat("Ж", 16), 2}, {strings.Repeat("𝐖", 16), 2}, {strings.Repeat("→", 16), 2},
	// 补充平面汉字（CJK 扩展 B 起，U+20000+）：不在 cjkRanges 里，按 2 计、需要折行点——审查者在 wine 里实测 9 行×21 个放不下
	{strings.Repeat("\U00020000", 16), 2}, {strings.Repeat("\U0002FFFF", 16), 2},
}

func TestDisplayLinesMatchesTheSharedVectors(t *testing.T) {
	for _, v := range displayLineVectors {
		if got := displayLines(v.text); got != v.lines {
			t.Fatalf("displayLines(%.20q...)=%d want %d", v.text, got, v.lines)
		}
	}
}

// DrawText 把 CR、VT、FF 等也当换行；估算若只认 LF，就会把「字\r」×7+「字」×186 当成两三行，实际排成 8 行以上被裁掉。
func TestAllLineSeparatorsAreMeasuredAsLineBreaks(t *testing.T) {
	for _, sep := range []string{"\r", "\r\n", "\v", "\f", "\x1c", "\u0085", "\u2028", "\u2029"} {
		if got := displayLines("甲" + sep + "乙" + sep + "丙"); got != 3 {
			t.Fatalf("separator %q counted as %d lines, want 3", sep, got)
		}
		if got := displayLines(strings.Repeat("字", 186) + strings.Repeat(sep+"字", 7)); got != 14 {
			t.Fatalf("separator %q: displayLines=%d, want 14", sep, got)
		}
	}
	// 估算本身也必须把 CR 当换行：同一段文字用 CR 和 LF 分隔，估算结果要一样
	crMsg := strings.Repeat("字\r", 7) + strings.Repeat("字", 186)
	lfMsg := strings.Repeat("字\n", 7) + strings.Repeat("字", 186)
	for _, scale := range []int32{100, 146} {
		for _, px := range []int32{20, 28, 40} {
			if textFits(crMsg, px, 984, 258) != textFits(lfMsg, px, 984, 258) {
				t.Fatalf("scale %d px %d: CR and LF separated text were measured differently", scale, px)
			}
		}
	}
}

// 核心保证：只要文案满足下发规则（≤200 字且显示行数 ≤noticeMaxLines），在所有屏幕与 DPI 缩放下都必须完整放得下，
// 且选的字号是放得下的最大值。用「一条长行 + 若干单字短行」的最坏组合穷举，加确定性随机语料。
// 之前只测「200 字一行」和「8 个短行」，漏掉了二者的组合。
func TestEveryAllowedMessageFitsOnEveryScreenAndScale(t *testing.T) {
	var msgs []string
	for lines := 1; lines <= noticeMaxLines; lines++ {
		for long := 0; long <= 200; long += 3 { // 步长 3 已覆盖所有「折行边界」附近的组合；穷举步长 1 在 -race 下要 20 多秒
			m := strings.Repeat("字", long) + strings.Repeat("\n字", lines-1)
			if len([]rune(m)) <= 200 && displayLines(m) <= noticeMaxLines {
				msgs = append(msgs, m)
			}
		}
	}
	rng := rand.New(rand.NewSource(7))
	alphabet := []rune("缺考请点击确定ABCabc123，。 ")
	for i := 0; i < 300; i++ {
		var b strings.Builder
		for n := rng.Intn(200); n > 0; n-- {
			if rng.Intn(14) == 0 {
				b.WriteByte('\n')
			} else {
				b.WriteRune(alphabet[rng.Intn(len(alphabet))])
			}
		}
		if m := b.String(); len([]rune(m)) <= 200 && displayLines(m) <= noticeMaxLines {
			msgs = append(msgs, m)
		}
	}
	if len(msgs) < 300 {
		t.Fatalf("test corpus too small: %d", len(msgs))
	}
	screens := []struct{ w, h, sh int32 }{{819, 458, 768}, {768, 430, 720}, {720, 420, 675}, {720, 420, 768}, {1100, 616, 1080}, {1100, 620, 1440}}
	for _, s := range screens {
		for scale := int32(100); scale <= 146; scale += 6 {
			if scale > s.w*100/720 {
				continue // showNotice 会把缩放钳到 width*100/720
			}
			for _, msg := range msgs {
				h, px := fitNotice(msg, s.w, s.h, s.sh, scale)
				bodyW, bodyH := s.w-80*scale/100, h-248*scale/100
				if h > noticeHeightCap || h < s.h || px < noticeFontMinPixels || px > noticeFontMax*scale/100 {
					t.Fatalf("screen %dx%d scale %d: out of range h=%d px=%d for %.30q", s.w, s.h, scale, h, px, msg)
				}
				if !textFits(msg, px, bodyW, bodyH) {
					t.Fatalf("screen %dx%d scale %d: does NOT fit at %dpx/%dpx tall: %d runes, %d display lines, %.30q", s.w, s.h, scale, px, h, len([]rune(msg)), displayLines(msg), msg)
				}
				if top := noticeFontMax * scale / 100; px+2 <= top && textFits(msg, px+2, bodyW, bodyH) {
					t.Fatalf("screen %dx%d scale %d: %dpx is needlessly small (%dpx fits) for %.30q", s.w, s.h, scale, px, px+2, msg)
				}
			}
		}
	}
}

func TestShortTextNeverShrinksNeedlessly(t *testing.T) {
	_, mid := fitNotice(strings.Repeat("字", 40), 819, 458, 768, 100)
	_, short := fitNotice("请点击确定", 819, 458, 768, 100)
	_, long := fitNotice(strings.Repeat("字", 200), 819, 458, 768, 100)
	if short != 40 {
		t.Fatalf("short text shrank to %d", short)
	}
	if long >= mid || mid > short {
		t.Fatalf("longer text must not get a bigger font: short=%d mid=%d long=%d", short, mid, long)
	}
}

// 估算会乐观（英文按词折行、行高以字体为准），所以 Windows 上传给 layoutNotice 的是真实度量。
// 这里用一个比估算悲观 1.5 倍的「真实度量」：layoutNotice 必须据此继续缩字号/加高窗口，而不是照估算的结果走。
func TestLayoutFollowsARealMeasurementThatIsMorePessimisticThanTheEstimate(t *testing.T) {
	msg := strings.Repeat("字", 120)
	estH, estPx := fitNotice(msg, 819, 458, 768, 100)
	pessimistic := func(px, bodyW, bodyH int32) bool { return textFits(msg, px*3/2, bodyW, bodyH) }
	h, px := layoutNotice(819, 458, 768, 100, pessimistic)
	if px >= estPx && h <= estH {
		t.Fatalf("layout ignored the pessimistic measurement: est h=%d px=%d, got h=%d px=%d", estH, estPx, h, px)
	}
	if !pessimistic(px, 819-80, h-248) && px > noticeFontMinPixels {
		t.Fatalf("layout returned a size that its own measurement says does not fit: h=%d px=%d", h, px)
	}
	// 度量说「怎么都放不下」时不能死循环，也不能越过契约：用最大窗口 + 最小字号
	h, px = layoutNotice(819, 458, 768, 100, func(int32, int32, int32) bool { return false })
	if px != noticeFontMinPixels || h > noticeHeightCap {
		t.Fatalf("hopeless text: h=%d px=%d", h, px)
	}
}

// DrawText 不会拆没有空格的超长 ASCII 串（URL、长数字、200 个 W），它们横向溢出窗口、被裁掉——
// 这比「连续宽字母」常见得多。客户端显示前给这类超长串插入折行点；正常文字原样不动。
func TestPopupTextBreaksOnlyOverlongUnspacedRuns(t *testing.T) {
	for _, same := range []string{"请点击确定填写缺考信息", "https://school.example.edu/notice", "一二三 abc def\nsecond line", strings.Repeat("W", 36), "", strings.Repeat("字", 200)} {
		if got := popupText(same); got != same {
			t.Fatalf("text without an overlong ASCII run was altered: %q -> %q", same, got)
		}
	}
	for name, long := range map[string]string{
		"200 W":  strings.Repeat("W", 200),
		"数字串":    strings.Repeat("1234567890", 10),
		"长 URL":  "https://school.example.edu/notice/" + strings.Repeat("20261025", 15),
		"中文里夹长串": "请访问" + strings.Repeat("a", 60) + "获取",
	} {
		got := popupText(long)
		run, longest := 0, 0
		for _, r := range got {
			if r < 128 && r != ' ' && r != '\n' {
				if run++; run > longest {
					longest = run
				}
			} else {
				run = 0
			}
		}
		if longest > 12 {
			t.Fatalf("%s: still has an unbreakable run of %d chars: %q", name, longest, got)
		}
		if strings.ReplaceAll(got, " ", "") != strings.ReplaceAll(long, " ", "") {
			t.Fatalf("%s: popupText changed characters, not just inserted breaks: %q", name, got)
		}
	}
	if popupText("甲\r乙\u2028丙") != "甲\n乙\n丙" {
		t.Fatal("popupText must also normalize line separators")
	}
}

// 超长串折行之后，最坏的一条（200 个 W，每个按 1em 宽）在最窄最矮的几何、最小字号下必须放得下——
// 之前它是文档里的「已知上限」，其实只要给折行点就不是上限。
func TestOverlongRunsFitAtTheMinimumFontOnTheTightestGeometry(t *testing.T) {
	const minPx = noticeFontMinPixels
	bodyW, bodyH := int32(720-80), int32(620-248*146/100) // 窗口最窄 + 正文最矮
	for name, msg := range map[string]string{"200 W": strings.Repeat("W", 200), "数字串": strings.Repeat("1234567890", 20), "URL": "https://a.example.edu/" + strings.Repeat("20261025", 22)} {
		words := strings.Fields(popupText(msg))
		perLine := int(bodyW*95/100) / (breakEvery*minPx + minPx) // 每个词最多 breakEvery 个 1em 宽字符 + 1 个空格
		if perLine < 1 {
			perLine = 1
		}
		lines := (len(words) + perLine - 1) / perLine
		if int32(lines)*minPx*135/100 > bodyH {
			t.Fatalf("%s: %d words need %d lines (%dpx) > body %dpx even at %dpx", name, len(words), lines, int32(lines)*minPx*135/100, bodyH, minPx)
		}
	}
}

// 非 ASCII 的无空格长串（带音标的拉丁字母、emoji、希腊/西里尔字母）DrawText 同样不拆；CJK 汉字/假名/谚文/全角字符 DrawText 能逐字折行，不需要处理。
// 审查者在 wine 里实测 200 个 é 要 1800px、30 个 😀 要 960px，而服务端放行。
func TestNonAsciiUnspacedRunsGetBreakPointsButCJKIsUntouched(t *testing.T) {
	untouched := []string{"请点击确定填写缺考信息", strings.Repeat("字", 200), strings.Repeat("１２３４５６", 13), strings.Repeat("あ", 80), strings.Repeat("한", 80),
		"résumé café", strings.Repeat("é", 12), "😀😀😀 ok", "（全角括号）。、"}
	for _, s := range untouched {
		if got := popupText(s); got != s {
			t.Fatalf("text DrawText can already wrap was altered: %q -> %q", s, got)
		}
	}
	for name, long := range map[string]string{
		"60 Ŵ": strings.Repeat("Ŵ", 60), "30 emoji": strings.Repeat("😀", 30), "200 é": strings.Repeat("é", 200), "希腊": strings.Repeat("ωΩ", 40),
		"混合": strings.Repeat(strings.Repeat("W", 35)+"é", 5), "夹在汉字里": "请看" + strings.Repeat("é", 60) + "结束",
	} {
		got := popupText(long)
		if longest := longestUnbreakableRun(got); longest > 12 {
			t.Fatalf("%s: still has an unbreakable run of %d runes: %q", name, longest, got)
		}
		if strings.ReplaceAll(got, " ", "") != strings.ReplaceAll(long, " ", "") {
			t.Fatalf("%s: popupText changed characters, not just inserted breaks", name)
		}
	}
}

// 不能把一个组合字符序列从中间拆开（ZWJ emoji、变体选择符、组合音标），否则显示就坏了。
func TestBreakPointsNeverSplitAGraphemeSequence(t *testing.T) {
	family := "👨\u200d👩\u200d👧\u200d👦"
	accented := "e\u0301"
	for name, unit := range map[string]string{"ZWJ 家庭": family, "组合音标": accented, "变体选择符": "☺\ufe0f"} {
		got := popupText(strings.Repeat(unit, 40))
		for _, bad := range []string{" \u200d", "\u200d ", " \u0301", " \ufe0f"} {
			if strings.Contains(got, bad) {
				t.Fatalf("%s: a break point was inserted inside a sequence: %q", name, got)
			}
		}
		if strings.ReplaceAll(got, " ", "") != strings.Repeat(unit, 40) {
			t.Fatalf("%s: characters changed", name)
		}
	}
}

func longestUnbreakableRun(s string) int {
	run, longest := 0, 0
	for _, r := range s {
		if r == ' ' || r == '\n' || r == '\t' || drawTextCanWrapBetween(r) {
			run = 0
			continue
		}
		if run++; run > longest {
			longest = run
		}
	}
	return longest
}

// 降级（逐字折行）同样不能把组合字符序列从中间拆开。
func TestAggressiveFallbackNeverSplitsAGraphemeSequence(t *testing.T) {
	for name, unit := range map[string]string{"ZWJ 家庭": "👨\u200d👩\u200d👧\u200d👦", "组合音标": "e\u0301", "变体选择符": "☺\ufe0f", "肤色": "👍\U0001F3FD"} {
		src := strings.Repeat(unit, 20)
		got := breakRuns(src, true)
		for _, bad := range []string{" \u200d", "\u200d ", " \u0301", " \ufe0f", " \U0001F3FD"} {
			if strings.Contains(got, bad) {
				t.Fatalf("%s: fallback split a sequence: %q", name, got)
			}
		}
		if strings.ReplaceAll(got, " ", "") != src {
			t.Fatalf("%s: characters changed", name)
		}
		if !strings.Contains(got, " ") {
			t.Fatalf("%s: aggressive mode inserted no break points at all", name)
		}
	}
}

// 模拟 DrawText(DT_WORDBREAK)：只在空格/换行处折行，不拆词；CJK 逐字可折；字符宽度取保守值（普通 1em，emoji 2em）。
// 返回 (最宽一行, 总高)。这是对 Win32 行为的保守模型，用来检验「度量说放不下时的降级」这条逻辑，不替代真机度量。
func simulateDrawText(text string, px, bodyW int32) (int32, int32) {
	text = normalizeBreaks(text)
	glyph := func(r rune) int32 {
		return int32(runeWeight(r)) * px
	}
	var maxW, lineW, lines int32 = 0, 0, 1
	flushWord := func(w int32) {
		if lineW > 0 && lineW+px/2+w > bodyW {
			lines++
			lineW = 0
		}
		if lineW > 0 {
			lineW += px / 2
		}
		lineW += w
		if lineW > maxW {
			maxW = lineW
		}
	}
	var word int32
	for _, r := range text + "\n" {
		switch {
		case r == ' ' || r == '\n' || r == '\t':
			if word > 0 {
				flushWord(word)
				word = 0
			}
			if r == '\n' {
				lines++
				lineW = 0
			}
		case drawTextCanWrapBetween(r):
			if word > 0 {
				flushWord(word)
				word = 0
			}
			flushWord(glyph(r))
		default:
			word += glyph(r)
		}
	}
	if lineW == 0 && lines > 1 {
		lines-- // 末尾补的那个 \n 不算一行
	}
	return maxW, lines * px * 135 / 100
}

func simulatedFits(text string, px, bodyW, bodyH int32) bool {
	w, h := simulateDrawText(text, px, bodyW)
	return w <= bodyW && h <= bodyH
}

// 核心：任何服务端会放行的文案，在最窄最矮的几何下，经「启发式折行点 → 度量不行再逐字折行」后都放得下。
// 审查者在 wine 里逐轮找出的反例（Ŵ、emoji、é、混合）以及 ASCII 反例一并固化。
func TestLayoutPopupFitsEverythingTheServerAllows(t *testing.T) {
	msgs := map[string]string{
		"60 Ŵ": strings.Repeat("Ŵ", 60), "30 emoji": strings.Repeat("😀", 30), "200 é": strings.Repeat("é", 200), "混合": strings.Repeat(strings.Repeat("W", 35)+"é", 5),
		"200 W": strings.Repeat("W", 200), "数字串": strings.Repeat("1234567890", 20), "URL": "https://school.example.edu/notice/" + strings.Repeat("20261025", 20),
		"100 emoji": strings.Repeat("😀", 100), "希腊": strings.Repeat("ωΩ", 40), "ZWJ 链": strings.TrimSuffix(strings.Repeat("😀\u200d", 65), "\u200d"), "数学粗体": strings.Repeat("𝐖", 60), "箭头": strings.Repeat("→", 60), "汉字": strings.Repeat("缺考", 100), "短行": strings.Join([]string{"行", "行", "行", "行", "行", "行", "行", "行", "行"}, "\n"),
		"汉字夹长串": "请访问" + strings.Repeat("é", 150) + "获取", "默认": "请点击确定填写缺考信息",
		// 审查者的反例：每行 21 个 emoji ×9 行按旧规则算 9 行，实际每行折两行变 18 行；新规则按加权算，应被拒绝（见下面的专门断言）
		"9 行各 15 个 emoji": strings.TrimSuffix(strings.Repeat(strings.Repeat("😀", 15)+"\n", 9), "\n"), "符号": strings.Repeat("☀", 60),
	}
	for name, msg := range msgs {
		if len([]rune(msg)) > 200 || displayLines(msg) > noticeMaxLines {
			t.Fatalf("%s is not a message the server would accept", name)
		}
		for _, g := range []struct{ w, h, sh, sc int32 }{{720, 420, 675, 100}, {819, 458, 768, 100}, {1100, 616, 1080, 146}} {
			text, h, px, ok := layoutPopup(msg, g.w, g.h, g.sh, g.sc, simulatedFits)
			if !ok || !simulatedFits(text, px, g.w-80*g.sc/100, h-248*g.sc/100) {
				t.Fatalf("%s on %dx%d@%d: does not fit even after the fallback (px=%d h=%d)", name, g.w, g.h, g.sc, px, h)
			}
			if strings.ReplaceAll(strings.ReplaceAll(text, " ", ""), "\n", "") != strings.ReplaceAll(strings.ReplaceAll(normalizeBreaks(msg), " ", ""), "\n", "") {
				t.Fatalf("%s: characters changed, only breaks may be inserted", name)
			}
		}
	}
}

// 降级只在度量说放不下时才发生：能放得下的文案不能被逐字拆开。
func TestFallbackOnlyWhenTheMeasurementSaysItDoesNotFit(t *testing.T) {
	for _, msg := range []string{"请点击确定填写缺考信息", "https://school.example.edu/notice", strings.Repeat("W", 36), "résumé café"} {
		text, _, _, ok := layoutPopup(msg, 819, 458, 768, 100, simulatedFits)
		if !ok || text != popupText(msg) {
			t.Fatalf("%q was altered by the fallback although it fits: %q", msg, text)
		}
	}
	// 度量永远说放不下：降级后仍放不下，必须如实返回 ok=false（调用方记 WARNING），且不死循环
	_, _, px, ok := layoutPopup(strings.Repeat("é", 200), 720, 420, 675, 100, func(string, int32, int32, int32) bool { return false })
	if ok || px != noticeFontMinPixels {
		t.Fatalf("hopeless measurement: ok=%v px=%d", ok, px)
	}
}

// 审查反例：9 个硬行、每行 21 个 emoji（197 码点）。旧规则按字数算只有 9 个显示行被放行，实际每行 42em > 一行容量，折成 18 行裁尾。
// 现在 emoji 按 2 宽加权，这条必须被「显示行数」规则拒绝（服务端、管理端同一规则，Python 测试有同一向量）。
func TestWideGlyphMessagesAreRejectedByTheLineRule(t *testing.T) {
	bad := strings.TrimSuffix(strings.Repeat(strings.Repeat("😀", 21)+"\n", 9), "\n")
	if len([]rune(bad)) > 200 {
		t.Fatalf("test message is not within 200 chars: %d", len([]rune(bad)))
	}
	if displayLines(bad) <= noticeMaxLines {
		t.Fatalf("9x21 emoji counted as %d display lines; must exceed %d", displayLines(bad), noticeMaxLines)
	}
}

// 国旗（区域指示符成对）、标签序列（🏴 + U+E0020–E007F）和键帽等组合序列不能被从中间拆开，启发式与降级两种模式都一样。
func TestFlagsAndTagSequencesAreNeverSplit(t *testing.T) {
	scotland := "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"
	cases := map[string]string{
		"国旗对":    "a" + strings.Repeat("🇨🇳", 8),
		"奇数前缀国旗": "x" + strings.Repeat("🇨🇳", 20),
		"苏格兰旗":   strings.Repeat(scotland, 5),
		"键帽":     strings.Repeat("1\ufe0f\u20e3", 12),
	}
	for name, src := range cases {
		for _, aggressive := range []bool{false, true} {
			got := breakRuns(src, aggressive)
			if strings.ReplaceAll(got, " ", "") != src {
				t.Fatalf("%s: characters changed", name)
			}
			for _, field := range strings.Fields(got) {
				ri := 0
				for i, r := range []rune(field) {
					if r >= 0x1F1E6 && r <= 0x1F1FF {
						ri++
					}
					if i == 0 && (r >= 0xE0020 && r <= 0xE007F || r == 0xFE0F || r == 0x20E3) {
						t.Fatalf("%s (aggressive=%v): a piece starts in the middle of a sequence: %q", name, aggressive, got)
					}
				}
				if ri%2 != 0 {
					t.Fatalf("%s (aggressive=%v): a flag pair was split: %q", name, aggressive, got)
				}
			}
		}
	}
}

// 属性测试：随机生成「汉字/英文词/长串/emoji/符号/空格/换行」混合的文案，凡是满足服务端规则（≤200 字、显示行数 ≤9）的，
// 在最紧的几何下经 layoutPopup（含降级）都必须在保守的 DrawText 模型里放得下。这是为了不再靠审查者一轮一轮找反例。
func TestPropertyEverythingTheRuleAcceptsFits(t *testing.T) {
	rng := rand.New(rand.NewSource(20261025))
	pieces := []func() string{
		func() string { return strings.Repeat("字", 1+rng.Intn(40)) },
		func() string { return strings.Repeat("W", 1+rng.Intn(60)) },
		func() string { return strings.Repeat("😀", 1+rng.Intn(25)) },
		func() string { return strings.Repeat("é", 1+rng.Intn(40)) },
		func() string { return strings.Repeat("☀", 1+rng.Intn(20)) },
		func() string { return strings.Repeat("🇨🇳", 1+rng.Intn(10)) },
		func() string { return strings.TrimSuffix(strings.Repeat("😀\u200d", 1+rng.Intn(70)), "\u200d") }, // 病态的无限 ZWJ 链
		func() string { return strings.Repeat("𝐖", 1+rng.Intn(40)) }, func() string { return strings.Repeat("Ж", 1+rng.Intn(40)) }, func() string { return strings.Repeat("→", 1+rng.Intn(40)) },
		func() string { return "https://a.example.edu/" + strings.Repeat("0123456789", rng.Intn(5)) },
		func() string { return " " }, func() string { return " " }, func() string { return "\n" },
		// 多个硬行、每行很多宽字符：审查者的 9×21 emoji 反例就是这一类。让属性测试也能守住「行数规则」这一层，而不只是折行点
		func() string {
			return strings.TrimSuffix(strings.Repeat(strings.Repeat("😀", 5+rng.Intn(20))+"\n", 2+rng.Intn(8)), "\n")
		},
		func() string {
			return strings.TrimSuffix(strings.Repeat(strings.Repeat("W", 10+rng.Intn(40))+"\n", 2+rng.Intn(8)), "\n")
		},
	}
	geometries := []struct{ w, h, sh, sc int32 }{{720, 420, 675, 100}, {819, 458, 768, 100}, {1100, 616, 1080, 146}}
	accepted := 0
	for i := 0; i < 4000; i++ {
		var b strings.Builder
		for n := 1 + rng.Intn(9); n > 0; n-- {
			b.WriteString(pieces[rng.Intn(len(pieces))]())
		}
		msg := strings.TrimSpace(b.String())
		if msg == "" || len([]rune(msg)) > 200 || displayLines(msg) > noticeMaxLines {
			continue
		}
		accepted++
		for _, g := range geometries {
			text, h, px, ok := layoutPopup(msg, g.w, g.h, g.sh, g.sc, simulatedFits)
			if !ok || !simulatedFits(text, px, g.w-80*g.sc/100, h-248*g.sc/100) {
				t.Fatalf("accepted by the rule (%d runes, %d display lines) but does not fit on %dx%d@%d: %q", len([]rune(msg)), displayLines(msg), g.w, g.h, g.sc, msg)
			}
		}
	}
	if accepted < 300 {
		t.Fatalf("property corpus too small: %d accepted", accepted)
	}
}

// 审查反例：数学粗体 𝐖(U+1D416) 在 U+1F000 以下，旧权重按 1 算，9 行×21 个实际要折成 18 行。现在「未知一律按 2」。
func TestUnknownWideScriptsAreWeightedConservatively(t *testing.T) {
	for name, line := range map[string]string{"数学粗体": strings.Repeat("𝐖", 21), "箭头": strings.Repeat("→", 21), "西里尔": strings.Repeat("Ж", 21), "扩展 B 汉字": strings.Repeat("\U00020000", 21), "扩展 F 汉字": strings.Repeat("\U0002FFFF", 21)} {
		msg := strings.TrimSuffix(strings.Repeat(line+"\n", 9), "\n")
		if displayLines(msg) <= noticeMaxLines {
			t.Fatalf("%s: 9 lines x 21 wide chars counted as %d display lines, must exceed %d", name, displayLines(msg), noticeMaxLines)
		}
	}
}

// 无限长的 ZWJ 链（😀‍😀‍😀…）不能被当成一个不可拆的整体：真实组合序列最多十来个码点，超过就强制可断。
// 审查反例：65 个 😀 用 ZWJ 连起来，129 码点、加权 258 → 9 行被放行，旧实现整串不可拆，16px 下横溢 3104px。
func TestPathologicalZWJChainStillGetsBreakPoints(t *testing.T) {
	chain := strings.TrimSuffix(strings.Repeat("😀\u200d", 65), "\u200d")
	for _, aggressive := range []bool{false, true} {
		got := breakRuns(chain, aggressive)
		for _, field := range strings.Fields(got) {
			if n := len([]rune(field)); n > 16 { // 字面量上限：真实序列最长 7 个码点，16 留足余量；不拿被测常量当预期值
				t.Fatalf("aggressive=%v: a piece of %d runes is still unbreakable", aggressive, n)
			}
		}
		if strings.ReplaceAll(got, " ", "") != chain {
			t.Fatalf("aggressive=%v: characters changed", aggressive)
		}
	}
	if displayLines(chain) > noticeMaxLines {
		t.Fatalf("the reviewer's chain must be one the rule accepts (got %d display lines)", displayLines(chain))
	}
}

// 降级路径必须真的被用到：度量要求「没有超过 2 个字符的不可断串」，启发式（每 6 个一断）满足不了，只有逐字折行能满足。
// 之前所有测试里度量模型都很宽松，把 aggressive 改成 false 全部仍然绿——降级成了没有被检验过的代码。
func TestFallbackIsReallyUsedWhenTheMeasurementDemandsIt(t *testing.T) {
	msg := strings.Repeat("é", 30)
	strict := func(text string, _, _, _ int32) bool { return longestUnbreakableRun(text) <= 2 }
	if heuristic := breakRuns(msg, false); strict(heuristic, 0, 0, 0) {
		t.Fatalf("test premise broken: the heuristic text already satisfies the strict measurement: %q", heuristic)
	}
	text, _, _, ok := layoutPopup(msg, 819, 458, 768, 100, strict)
	if !ok || longestUnbreakableRun(text) > 1 {
		t.Fatalf("fallback was not applied: ok=%v text=%q", ok, text)
	}
}
