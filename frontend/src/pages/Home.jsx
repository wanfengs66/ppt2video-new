import { useNavigate } from 'react-router-dom'
import { Button, Typography, Space } from 'antd'
import {
  FileTextOutlined,
  SoundOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
  HistoryOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'

const { Title, Paragraph, Text } = Typography

const features = [
  {
    kicker: 'Narration',
    icon: <FileTextOutlined />,
    title: '智能解说词',
    desc: 'AI 逐页理解幻灯片内容，自动生成口语化解说词，支持上下文连贯与逐页精修',
  },
  {
    kicker: 'Voice',
    icon: <SoundOutlined />,
    title: '高质量配音',
    desc: 'CosyVoice2 语音合成引擎，多种音色可选，自动生成逐句对齐的字幕',
  },
  {
    kicker: 'Render',
    icon: <VideoCameraOutlined />,
    title: '一键成片',
    desc: '画面、配音、字幕自动合成，输出 720p MP4 专业演示视频',
  },
  {
    kicker: 'Batch',
    icon: <ThunderboltOutlined />,
    title: '异步批量处理',
    desc: '大批量页面自动排队处理，实时进度可见，处理中可预览已完成部分',
  },
]

const steps = [
  { num: '01', label: '上传 PPT' },
  { num: '02', label: 'AI 生成解说词' },
  { num: '03', label: '合成配音字幕' },
  { num: '04', label: '导出成片' },
]

export default function Home() {
  const navigate = useNavigate()

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-warm)', overflow: 'hidden', position: 'relative' }}>
      {/* 背景光晕：天青蓝 + 奶油暖光 */}
      <div className="glow-orb" style={{ width: 560, height: 560, top: -200, left: '10%', background: 'rgba(74,181,224,0.13)' }} />
      <div className="glow-orb" style={{ width: 420, height: 420, top: 300, right: '-6%', background: 'rgba(253,241,225,0.05)' }} />

      {/* Header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="brand-mark">P</div>
          <Text strong style={{ fontSize: 18, letterSpacing: 0.3, fontFamily: 'var(--font-display)', fontWeight: 500 }}>
            PPT2Video
          </Text>
        </div>
        <Space size={12}>
          <Button icon={<HistoryOutlined />} ghost onClick={() => navigate('/history')}>
            历史记录
          </Button>
          <Button
            type="primary"
            className="btn-gradient"
            icon={<VideoCameraOutlined />}
            onClick={() => navigate('/studio')}
            style={{ borderRadius: 999 }}
          >
            进入工作台
          </Button>
        </Space>
      </header>

      {/* Hero */}
      <section style={{ textAlign: 'center', padding: '88px 48px 72px', position: 'relative' }} className="fade-up">
        {/* 胶囊标签（Mostar hero-tags 风格） */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 32 }}>
          {['AI 解说词', '语音合成', '自动字幕'].map((t) => (
            <span key={t} style={{
              minHeight: 38,
              display: 'inline-flex',
              alignItems: 'center',
              padding: '0 20px',
              borderRadius: 999,
              border: '1px solid var(--border-strong)',
              color: 'var(--text-gray)',
              fontSize: 13,
              background: 'rgba(253,241,225,0.04)',
            }}>
              {t}
            </span>
          ))}
        </div>

        <Title
          className="text-gradient"
          style={{ fontSize: 68, margin: '0 0 24px', letterSpacing: -0.5, lineHeight: 1.05 }}
        >
          把 PPT 变成<br />会讲解的视频
        </Title>
        <Paragraph style={{
          fontSize: 17,
          color: 'var(--text-gray)',
          maxWidth: 560,
          margin: '0 auto 44px',
          lineHeight: 1.9,
          fontWeight: 500,
          textShadow: '0 2px 18px rgba(0,0,0,0.42)',
        }}>
          上传演示文稿，AI 自动理解每页内容、撰写解说词、合成配音与字幕，几分钟内输出专业级演示视频
        </Paragraph>

        <Space size={16}>
          <Button
            type="primary"
            size="large"
            className="btn-gradient"
            onClick={() => navigate('/studio')}
            style={{ height: 54, fontSize: 17, paddingInline: 42, borderRadius: 999, fontWeight: 600 }}
          >
            立即开始创作
          </Button>
          <Button
            size="large"
            className="btn-ghost-dark"
            onClick={() => navigate('/history')}
            style={{ height: 54, fontSize: 16, paddingInline: 32, borderRadius: 999 }}
          >
            查看历史作品
          </Button>
        </Space>

        {/* 流程步骤 */}
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          marginTop: 76,
          flexWrap: 'wrap',
        }}>
          {steps.map((s, i) => (
            <div key={s.num} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ textAlign: 'center', padding: '0 8px' }}>
                <div style={{
                  fontSize: 13,
                  fontFamily: 'var(--font-display)',
                  color: 'var(--text-light)',
                  letterSpacing: 2,
                  marginBottom: 6,
                }}>{s.num}</div>
                <div style={{ fontSize: 15, color: 'var(--text-dark)', fontWeight: 600 }}>{s.label}</div>
              </div>
              {i < steps.length - 1 && (
                <ArrowRightOutlined style={{ color: 'var(--text-light)', margin: '18px 22px 0', fontSize: 13 }} />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Features：奶油卡片（Mostar sight-card 风格） */}
      <section style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 48px 96px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 20,
        }}>
          {features.map((f, i) => (
            <div
              key={i}
              className="paper-card paper-card-hover fade-up"
              style={{ padding: '26px 26px 24px', animationDelay: `${i * 0.08}s` }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 40 }}>
                <span style={{
                  fontSize: 12,
                  fontWeight: 500,
                  letterSpacing: 1.5,
                  textTransform: 'uppercase',
                  color: 'rgba(17,20,17,0.55)',
                }}>
                  {f.kicker}
                </span>
                <div style={{
                  width: 46,
                  height: 46,
                  borderRadius: 12,
                  background: 'rgba(17,20,17,0.06)',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 21,
                  color: 'var(--ink)',
                }}>
                  {f.icon}
                </div>
              </div>
              <div style={{ fontSize: 19, fontWeight: 800, marginBottom: 10, color: 'var(--ink)', lineHeight: 1.2 }}>{f.title}</div>
              <div style={{ fontSize: 13.5, color: 'rgba(17,20,17,0.62)', lineHeight: 1.75 }}>{f.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer style={{
        textAlign: 'center',
        padding: '22px',
        color: 'var(--text-light)',
        borderTop: '1px solid var(--border)',
        fontSize: 13,
      }}>
        PPT2Video &copy; {new Date().getFullYear()} · 本地运行模式
      </footer>
    </div>
  )
}
