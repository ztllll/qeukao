package main

import (
	"strings"
	"unicode"
)

// 弹窗正文的自适应排版（纯函数，不依赖 Windows，便于测试）。
//
// 管理员可以自定义最长 200 字的弹窗文案。窗口的物理尺寸被契约封顶在 1100x620，
// 所以文案长时必须缩字号、必要时把窗口加高；这里的字号全部用「物理像素」计算：
// 缩放越高，同样的逻辑字号占的物理像素越多，窗口却不会变大——如果下限按逻辑像素定，高分屏上反而放不下。
// 规则：默认文案保持大字（40 逻辑像素）；放不下就逐级缩小，仍放不下再把窗口加高到上限；物理字号最低 16px。
// 估算偏保守（汉字 = 1 个字号宽，ASCII 按 0.6，行高 1.35，宽度留 5% 边距）。

// 与服务端 qk_agents.py、管理端 static/admin.js 保持一致：每个硬行按 noticeLineChars 字折行累加，最多 noticeMaxLines 行。
// 服务端在下发时就按这条规则拒绝，所以客户端收到的文案一定满足它；fitNotice 在此前提下保证放得下。
const (
	noticeLineChars = 30
	noticeMaxLines  = 9
)

// popupText 是真正交给弹窗显示（度量和绘制）的文字：换行字符规范成 \n，并给「没有空格的超长 ASCII 串」插折行点。
// DrawText 的 DT_WORDBREAK 只在空格处折行、不会拆长词（URL、长数字、200 个 W 会横向溢出被裁掉）。
// ASCII 非空白连续串长度 > overlongRun(36) 时每 breakEvery 个字符插一个空格；含非 ASCII 的连续串用更严的阈值（见 wideRun）；
// 汉字等 CJK 本身可逐字折行，正常文字原样不动。组合字符序列（ZWJ emoji、组合音标、变体选择符）不会从中间拆开。
// 阈值由最窄几何推出：窗口最窄 720 → 正文可用约 (720-80)*0.95=608px，16px 下最宽的 ASCII 字符（W≈1em）一行能放 38 个；
// 所以不超过 36 个字符的连续串缩到最小字号一定放得下，不必拆（普通网址、编号原样显示）；更长的才插折行点。
const (
	overlongRun = 36
	breakEvery  = 12
)

// 非 ASCII（带音标的拉丁字母、希腊/西里尔、emoji…）的连续串 DrawText 同样不拆，而且单个字符可能宽到 2em（emoji），
// 所以它们用更严的阈值：连续 > wideRun(12) 个就每 wideChunk(8) 个插一个折行点（8×2em×16px=256px，窄窗口一行放得下）。
// CJK（汉字/假名/谚文/全角字符/CJK 标点）DrawText 本身可以逐字折行，不处理。
const (
	wideRun   = 12
	wideChunk = 6 // 6×2em×16px=192px，窄窗口一行放 3 个；200 个 emoji 级别的最坏情况正好 12 行
)

// cjkRanges：CJK 与全角字符。DrawText(DT_WORDBREAK) 在它们之间可以逐字折行，宽度约 1em。
// 同一张表在 qk_agents.py(_CJK_RANGES)、static/admin.js(CJK_RANGES) 里各有一份，必须逐项一致（权重规则靠它）。
var cjkRanges = [][2]rune{{0x1100, 0x11FF}, {0x2E80, 0x2FDF}, {0x3000, 0x30FF}, {0x3100, 0x312F}, {0x3400, 0x4DBF}, {0x4E00, 0x9FFF},
	{0xAC00, 0xD7AF}, {0xF900, 0xFAFF}, {0xFE30, 0xFE4F}, {0xFF00, 0xFFEF}}

// 注意：补充平面汉字（U+20000 起）故意不在表里——雅黑没有这些字形，回退字体的宽度与能否逐字折行都没验证过，
// 按「未知一律 2、给折行点」处理（审查者实测 9 行×21 个按 1 计会放不下）。

func isCJK(r rune) bool {
	for _, rg := range cjkRanges {
		if r >= rg[0] && r <= rg[1] {
			return true
		}
	}
	return false
}

// drawTextCanWrapBetween 报告 r 前后 DrawText 本身就能折行（CJK 与全角字符），这类字符不计入「不可断连续串」。
func drawTextCanWrapBetween(r rune) bool { return isCJK(r) }

// maxCluster：一个组合序列（ZWJ emoji、旗帜、带肤色…）最多这么多个码点。真实序列最长十来个（家庭 7、旗帜 7）；
// 超过就不再当作「必须连在一起」，否则无限长的 ZWJ 链成了一个拆不开的超宽词，横溢被裁。
const maxCluster = 12

// continuesGrapheme 报告 r 是否必须和前一个字符连在一起显示（组合音标、变体选择符、ZWJ 及其后一个字符）。
func continuesGrapheme(r, prev rune) bool {
	return unicode.In(r, unicode.Mn, unicode.Me, unicode.Mc) || r == 0x200D || prev == 0x200D || (r >= 0xFE00 && r <= 0xFE0F) || (r >= 0x1F3FB && r <= 0x1F3FF) ||
		(r >= 0xE0020 && r <= 0xE007F) // 标签序列（🏴󠁧󠁢󠁳󠁣󠁴󠁿 这类旗帜）：标签字符必须跟在前一个字符后面
}

func isRegionalIndicator(r rune) bool { return r >= 0x1F1E6 && r <= 0x1F1FF }

func popupText(text string) string { return breakRuns(normalizeBreaks(text), false) }

// breakRuns 给不可折行的连续串插折行点。aggressive=true 是降级用的：除 CJK 外每个字符（组合序列算一个）自成一个词，
// 只在真实度量说「放不下」时才使用，用显示上的难看换完整可见。
func breakRuns(text string, aggressive bool) string {
	var out strings.Builder
	var run []rune
	wide := false
	flush := func() {
		limit, chunkSize := overlongRun, breakEvery
		if wide {
			limit, chunkSize = wideRun, wideChunk
		}
		if aggressive {
			limit, chunkSize = 1, 1
		}
		if len(run) > limit {
			chunk, cluster := 0, 0
			var prev rune
			ri := 0 // 连续区域指示符的个数：国旗由两个一组，第二个必须紧跟第一个
			for _, r := range run {
				if isRegionalIndicator(r) {
					ri++
				} else {
					ri = 0
				}
				continues := continuesGrapheme(r, prev) || (isRegionalIndicator(r) && ri%2 == 0)
				if continues && cluster >= maxCluster {
					continues = false // 病态的超长链：强制可断
				}
				if !continues {
					cluster = 0
				}
				if chunk >= chunkSize && !continues {
					out.WriteByte(' ')
					chunk = 0
				}
				out.WriteRune(r)
				chunk++
				cluster++
				prev = r
			}
		} else {
			out.WriteString(string(run))
		}
		run, wide = run[:0], false
	}
	for _, r := range text {
		if r == ' ' || r == '\n' || r == '\t' || drawTextCanWrapBetween(r) {
			flush()
			out.WriteRune(r)
			continue
		}
		if r >= 128 {
			wide = true
		}
		run = append(run, r)
	}
	flush()
	return out.String()
}

// normalizeBreaks 把 DrawText 会当作换行的字符统一成 \n，让估算与实际排版、与服务端的规范化口径一致。
func normalizeBreaks(text string) string {
	return strings.NewReplacer("\r\n", "\n", "\r", "\n", "\v", "\n", "\f", "\n", "\x1c", "\n", "\x1d", "\n", "\x1e", "\n", "\u0085", "\n", "\u2028", "\n", "\u2029", "\n").Replace(text)
}

// runeWeight：一个字符占几个「字符宽」。宽字符（emoji、符号、箭头、数学字母…）实际约 2em，按 2 计，
// 否则「每行 21 个」按字数只算 1 行、实际要折成 2 行。必须与 qk_agents.py 的 _weight、admin.js 的 messageWeight 一致。
func runeWeight(r rune) int {
	if r < 0x250 || (r >= 0x2000 && r <= 0x206F) || isCJK(r) {
		return 1 // ASCII、拉丁字母、常用标点（含 “”—…）、CJK：约 1em
	}
	return 2 // 其它一律按 2 计（emoji、符号、箭头、数学字母、希腊/西里尔…）：未知宁可保守，别靠逐类枚举
}

// displayLines 把 text 折算成「显示行数」：每个硬行（以 \n 分隔）至少 1 行，超过 noticeLineChars 字再多算一行。
func displayLines(text string) int {
	total, n := 0, 0
	for _, r := range normalizeBreaks(text) + "\n" {
		if r == '\n' {
			if n == 0 {
				total++
			} else {
				total += (n + noticeLineChars - 1) / noticeLineChars
			}
			n = 0
			continue
		}
		n += runeWeight(r)
	}
	return total
}

const (
	noticeFontMax       = 40  // 逻辑像素，乘以 DPI 缩放得到物理像素
	noticeFontMinPixels = 16  // 物理像素下限。按词折行的英文在最紧的几何（正文 258px 高）下 20px 要 10 行放不下，16px 才放得下
	noticeHeightCap     = 620 // 契约上限（物理像素）
)

// textFits 估算 text 在 bodyW x bodyH（物理像素）里、字号 px（物理像素）下能否完整显示。
func textFits(text string, px, bodyW, bodyH int32) bool {
	text = normalizeBreaks(text)
	usable := bodyW * 95 / 100
	if usable <= 0 || px <= 0 {
		return false
	}
	lines, width := int32(1), int32(0)
	for _, r := range text {
		if r == '\n' {
			lines++
			width = 0
			continue
		}
		w := px
		if r < 128 {
			w = px * 60 / 100
		}
		if width+w > usable {
			lines++
			width = 0
		}
		width += w
	}
	return lines*px*135/100 <= bodyH
}

// layoutPopup 决定弹窗最终显示的文字、窗口高度和字号。measure 是「这段文字在 px 字号、bodyW×bodyH 的正文区里放不放得下」的判定
// （Windows 上是真实 DrawText 度量）。流程：先用启发式折行点（popupText）排版；度量仍说放不下，就降级为逐字折行再排一次。
// 返回的 ok=false 表示连降级后也放不下（调用方记 WARNING，照常弹出，不卡住考务流程）。
// 这样「完整可见」不再依赖我们对每种字符宽度的预判：预判错了，降级兜底。
func layoutPopup(text string, width, height, screenH, scale int32, measure func(text string, px, bodyW, bodyH int32) bool) (string, int32, int32, bool) {
	normalized := normalizeBreaks(text)
	try := func(t string) (int32, int32, bool) {
		h, px := layoutNotice(width, height, screenH, scale, func(px, bodyW, bodyH int32) bool { return measure(t, px, bodyW, bodyH) })
		return h, px, measure(t, px, width-80*scale/100, h-248*scale/100)
	}
	t := breakRuns(normalized, false)
	if h, px, ok := try(t); ok {
		return t, h, px, true
	}
	t = breakRuns(normalized, true)
	h, px, ok := try(t)
	return t, h, px, ok
}

// fitNotice 用估算判断「放不放得下」（纯函数，测试用；Windows 上实际排版用 layoutNotice + 真实 DrawText 度量）。
func fitNotice(text string, width, height, screenH, scale int32) (int32, int32) {
	return layoutNotice(width, height, screenH, scale, func(px, bodyW, bodyH int32) bool {
		return textFits(text, px, bodyW, bodyH)
	})
}

// layoutNotice 返回窗口高度与正文字号（都是物理像素）。width/height/screenH 也是物理像素，scale 是 DPI 百分比。
// fits(px, bodyW, bodyH) 回答「这个字号在 bodyW x bodyH 的正文区里能否完整显示」：
// 估算永远是估算（英文按词折行、字体度量、行高都与 DrawText 不同），所以 Windows 上传入的是真实 DrawText(DT_CALCRECT) 的度量。
func layoutNotice(width, height, screenH, scale int32, fits func(px, bodyW, bodyH int32) bool) (int32, int32) {
	maxH := int32(noticeHeightCap)
	if limit := screenH * 85 / 100; limit < maxH {
		maxH = limit
	}
	if maxH < height {
		maxH = height
	}
	bodyW := width - 80*scale/100
	for px := int32(noticeFontMax) * scale / 100; px >= noticeFontMinPixels; px -= 2 {
		for _, h := range []int32{height, maxH} {
			if fits(px, bodyW, h-248*scale/100) {
				return h, px
			}
		}
	}
	return maxH, noticeFontMinPixels // 极端情况（估算也放不下）：用最大窗口与最小字号
}
