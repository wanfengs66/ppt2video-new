import { useEffect, useState, useRef, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Layout, Upload, Button, Typography, Spin, message, Modal, Input,
  Select, Steps, Progress, Space, Tooltip, Badge, Switch,
} from 'antd'
import {
  UploadOutlined, FileTextOutlined, SoundOutlined, VideoCameraOutlined,
  FileDoneOutlined, RocketOutlined, EditOutlined, CheckCircleOutlined,
  LeftOutlined, RightOutlined, ExpandOutlined, HistoryOutlined,
  HomeOutlined, SoundFilled, DownloadOutlined,
} from '@ant-design/icons'
import useStudioStore from '../stores/studioStore'
import {
  uploadPPT, generateScript, saveScript,
  generateAudio, generateSrt, generateVideo, getVoices,
  asyncGenerateScriptList, getTaskStatus, restoreJob,
} from '../api'
const { Sider, Content } = Layout
const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

/* ───────────── 常量 ───────────── */
const VOICE_OPTIONS = [
  { label: 'Alex (男声)', value: 'male' },
  { label: 'Anna (女声)', value: 'female' },
]

/* ───────────── 主组件 ───────────── */
export default function Studio() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const store = useStudioStore()

  const [editingSlide, setEditingSlide] = useState(null)
  const [editText, setEditText] = useState('')
  const [previewImage, setPreviewImage] = useState('')
  const [previewVisible, setPreviewVisible] = useState(false)
  const [voices, setVoices] = useState([])
  const [selectedVoice, setSelectedVoice] = useState('FunAudioLLM/CosyVoice2-0.5B:alex')
  const [level, setLevel] = useState('text-understanding')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const pollRef = useRef(null)

  /* ── 初始化 ── */
  useEffect(() => {
    getVoices().then(r => {
      if (r.data?.voices) setVoices(r.data.voices)
    }).catch(() => {})
  }, [])

  /* ── 会话恢复 ── */
  useEffect(() => {
    const jobId = searchParams.get('job_id')
    if (!jobId) {
      // 没有 job_id 则重置为新任务
      store.reset()
      return
    }
    // 有 job_id 时恢复旧任务
      restoreJob(jobId).then(r => {
        const data = r.data
        store.setJobData({
          filePath: data.file_path,
          ossUrls: data.oss_urls,
          smartartSlides: data.smartart_slides || [],
        })
        // 恢复已生成的解说词
        const scripts = data.scripts || {}
        Object.entries(scripts).forEach(([idx, text]) => {
          store.setScript(Number(idx), text)
        })
        // 恢复音频状态
        const audioReady = data.audio_ready || {}
        Object.keys(audioReady).forEach(idx => {
          store.setAudioReady(Number(idx))
        })
        // 恢复字幕状态
        const srtReady = data.srt_ready || {}
        Object.keys(srtReady).forEach(idx => {
          store.setSrtReady(Number(idx))
        })
        // 恢复视频
        if (data.video_url) {
          store.setVideoUrl(data.video_url)
        }
        const restoredCount = Object.keys(scripts).length
        const extraMsg = restoredCount > 0
          ? `，已恢复 ${restoredCount} 页解说词`
          : ''
        message.success(`已恢复任务：${data.slide_count} 页${extraMsg}`)
        window.history.replaceState({}, document.title, '/studio')
      }).catch(() => message.error('恢复任务失败'))
  }, [searchParams])

  /* ── 异步任务轮询 ── */
  useEffect(() => {
    if (store.asyncTaskId && store.asyncTaskStatus === 'processing') {
      pollRef.current = setInterval(async () => {
        try {
          const res = await getTaskStatus(store.asyncTaskId)
          const t = res.data
          store.setAsyncTask(t.task_id, t.status, t.progress, t.message)

          // 实时呈现部分结果：处理中也有已生成的解说词
          if (t.result && Array.isArray(t.result) && t.result.length > 0) {
            store.setAllScripts(t.result)
          }

          if (t.status === 'completed' || t.status === 'failed') {
            clearInterval(pollRef.current)
            if (t.status === 'completed') {
              message.success('批量解说词生成完成')
              if (t.result && Array.isArray(t.result)) {
                store.setAllScripts(t.result)
              } else if (store.filePath) {
                try {
                  const rres = await import('../api').then(m => m.default.get(`/api/resources?file_path=${encodeURIComponent(store.filePath)}`))
                  if (rres.data?.scripts) store.setAllScripts(rres.data.scripts)
                } catch {}
              }
            } else {
              message.error('批量生成失败: ' + t.message)
            }
          }
        } catch { clearInterval(pollRef.current) }
      }, 2000)
    }
    return () => clearInterval(pollRef.current)
  }, [store.asyncTaskId, store.asyncTaskStatus])

  /* ── 上传处理 ── */
  const handleUpload = async (file) => {
    setUploading(true)
    setUploadProgress(0)
    try {
      const res = await uploadPPT(file, (p) => setUploadProgress(p))
      const data = res.data
      store.setJobData({
        filePath: data.file_path,
        ossUrls: data.oss_urls,
        smartartSlides: data.smartart_slides || [],
      })
      message.success(`上传成功：${Object.keys(data.oss_urls).length} 页`)
      // 保存到 localStorage
      localStorage.setItem('ppt2video_state', JSON.stringify({
        filePath: data.file_path,
        ossUrls: data.oss_urls,
        timestamp: Date.now(),
      }))
    } catch (err) {
      message.error('上传失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd 默认上传
  }

  /* ── 替换幻灯片图片 ── */
  const handleReplaceImage = async (slideIndex, file) => {
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch('/api/replace-slide-image', {
        method: 'POST',
        headers: { 'X-File-Path': store.filePath, 'X-Slide-Index': String(slideIndex) },
        body: formData,
      })
      const data = await res.json()
      if (res.ok) {
        store.setSlides({ ...store.slides, [String(slideIndex)]: data.image_url + '?t=' + Date.now() })
        // 仅替换图片，不解说词和音频字幕（修复渲染偏移不影响内容）
        message.success(data.message)
      } else {
        message.error(data.detail || '替换失败')
      }
    } catch (err) {
      message.error('替换失败: ' + err.message)
    }
  }

  /* ── 生成单页解说词 ── */
  const handleGenerateScript = async (slideIndex) => {
    store.setGeneratingScript?.(true)
    try {
      const ossUrl = store.slides[String(slideIndex)]
      const res = await generateScript({
        file_path: store.filePath,
        index: slideIndex,
        oss_url: ossUrl,
        understanding_level: level,
      })
      store.setScript(slideIndex, res.data.scripts || res.data.narration || res.data.text || '')
      message.success(`第 ${slideIndex} 页解说词已生成`)
    } catch (err) {
      message.error('生成失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      store.setGeneratingScript?.(false)
    }
  }

  /* ── 异步批量生成 ── */
  const handleAsyncGenerateAll = async () => {
    try {
      const ossUrls = { ...store.slides }
      const res = await asyncGenerateScriptList({
        file_path: store.filePath,
        oss_urls: ossUrls,
        understanding_level: level,
      })
      store.setAsyncTask(res.data.task_id, 'processing', 0, '任务已提交')
      message.success('异步任务已提交，请在进度条中查看')
    } catch (err) {
      message.error('提交失败: ' + (err.response?.data?.detail || err.message))
    }
  }

  /* ── 保存编辑的解说词 ── */
  const handleSaveScript = async (slideIndex, text) => {
    try {
      await saveScript({
        file_path: store.filePath,
        index: slideIndex,
        text,
      })
      store.setScript(slideIndex, text)
      message.success('已保存')
    } catch (err) {
      message.error('保存失败')
    }
  }

  /* ── 生成音频 ── */
  const handleGenerateAudio = async (slideIndex) => {
    store.setGeneratingAudio(true)
    try {
      await generateAudio({
        file_path: store.filePath,
        index: slideIndex,
        voice_type: selectedVoice,
      })
      store.setAudioReady(slideIndex)
      message.success(`第 ${slideIndex} 页音频已生成`)
    } catch (err) {
      message.error('音频生成失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      store.setGeneratingAudio(false)
    }
  }

  /* ── 生成字幕 ── */
  const handleGenerateSrt = async (slideIndex) => {
    store.setGeneratingSrt(true)
    try {
      await generateSrt({
        file_path: store.filePath,
        index: slideIndex,
      })
      store.setSrtReady(slideIndex)
      message.success(`第 ${slideIndex} 页字幕已生成`)
    } catch (err) {
      message.error('字幕生成失败')
    } finally {
      store.setGeneratingSrt(false)
    }
  }

  /* ── 一键生成全部音频+字幕 ── */
  const handleGenerateAllAudioAndSrt = async () => {
    store.setGeneratingAudio(true)
    try {
      // 1. 生成全部音频
      await generateAudio({
        file_path: store.filePath,
        voice_type: selectedVoice,
      })
      // 标记所有页音频就绪
      Object.keys(store.slides).forEach((idx) => store.setAudioReady(idx))
      message.success('全部音频已生成')
    } catch (err) {
      message.error('音频生成失败: ' + (err.response?.data?.detail || err.message))
      store.setGeneratingAudio(false)
      return
    }

    store.setGeneratingAudio(false)
    store.setGeneratingSrt(true)
    try {
      // 2. 生成全部字幕
      await generateSrt({
        file_path: store.filePath,
      })
      // 标记所有页字幕就绪
      Object.keys(store.slides).forEach((idx) => store.setSrtReady(idx))
      message.success('全部字幕已生成')
    } catch (err) {
      message.error('字幕生成失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      store.setGeneratingSrt(false)
    }
  }

  /* ── 生成视频 ── */
  const handleGenerateVideo = async () => {
    store.setGeneratingVideo(true)
    try {
      const res = await generateVideo({
        file_path: store.filePath,
        subtitle_enabled: store.subtitleEnabled,
      })
      const videoUrl = res.data.video_url || res.data.url
      store.setVideoUrl(videoUrl)
      message.success('视频生成完成！')
    } catch (err) {
      message.error('视频生成失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      store.setGeneratingVideo(false)
    }
  }

  /* ── 返回修改解说词 ── */
  const handleBackToEdit = () => {
    store.setVideoUrl('')  // 清除视频，显示编辑界面
    message.info('已返回编辑模式，修改解说词后请重新生成音频和视频')
  }

  /* ── 双击编辑解说词 ── */
  const startEdit = (slideIndex) => {
    setEditingSlide(slideIndex)
    setEditText(store.scripts[String(slideIndex)] || '')
  }

  const finishEdit = () => {
    if (editingSlide !== null) {
      handleSaveScript(editingSlide, editText)
    }
    setEditingSlide(null)
    setEditText('')
  }

  /* ── 排序的幻灯片列表 ── */
  const sortedSlides = Object.entries(store.slides)
    .sort(([a], [b]) => Number(a) - Number(b))

  const currentSlideUrl = store.slides[String(store.currentSlide)] || ''
  const currentScript = store.scripts[String(store.currentSlide)] || ''

  /* ── 无任务时显示上传界面 ── */
  if (!store.filePath) {
    return (
      <div style={{
        minHeight: '100vh',
        background: 'var(--bg-warm)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div className="glow-orb" style={{ width: 460, height: 460, top: '8%', left: '18%', background: 'rgba(74,181,224,0.1)' }} />
        <StudioHeader navigate={navigate} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 48 }}>
          <Upload.Dragger
            accept=".pptx,.ppt"
            showUploadList={false}
            beforeUpload={handleUpload}
            disabled={uploading}
            style={{
              width: 560,
              padding: '60px 40px',
              borderRadius: 16,
              background: 'var(--bg-panel)',
              border: '1.5px dashed var(--border-strong)',
            }}
          >
            {uploading ? (
              <div>
                <Spin size="large" />
                <Progress percent={uploadProgress} style={{ marginTop: 24, maxWidth: 360 }} />
                <Paragraph style={{ marginTop: 12, color: 'var(--text-gray)' }}>正在上传并处理 PPT...</Paragraph>
              </div>
            ) : (
              <div>
                <div style={{
                  width: 72,
                  height: 72,
                  margin: '0 auto 20px',
                  borderRadius: 18,
                  background: 'var(--primary-dim)',
                  border: '1px solid var(--primary-border)',
                  display: 'grid',
                  placeItems: 'center',
                }}>
                  <UploadOutlined style={{ fontSize: 34, color: 'var(--primary-light)' }} />
                </div>
                <Title level={3} style={{ marginBottom: 8, color: 'var(--text-dark)' }}>点击或拖拽 PPT 文件到此处</Title>
                <Paragraph style={{ color: 'var(--text-gray)', marginBottom: 0 }}>
                  支持 .pptx 格式，最大 200MB<br />
                  系统将自动拆分页面并生成缩略图
                </Paragraph>
              </div>
            )}
          </Upload.Dragger>
        </div>
      </div>
    )
  }

  /* ── 主工作台界面 ── */
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-warm)' }}>
      <StudioHeader navigate={navigate} hasJob />

      <Layout style={{
        margin: '12px auto',
        maxWidth: 1400,
        height: 'calc(100vh - 80px)',
        background: 'transparent',
        borderRadius: 16,
        overflow: 'hidden',
      }}>
        {/* 左侧：缩略图列表 */}
        <Sider
          width={180}
          style={{
            background: 'var(--bg-panel)',
            borderRadius: '16px 0 0 16px',
            overflow: 'auto',
            borderRight: '1px solid var(--border)',
          }}
        >
          <div style={{ padding: '12px 8px' }}>
            <Text strong style={{ display: 'block', padding: '4px 8px 12px', fontSize: 13, color: 'var(--text-gray)' }}>
              幻灯片 ({store.slideCount})
            </Text>
            {sortedSlides.map(([idx, url]) => (
              <div
                key={idx}
                onClick={() => store.setCurrentSlide(Number(idx))}
                style={{
                  padding: 6,
                  marginBottom: 4,
                  borderRadius: 8,
                  cursor: 'pointer',
                  background: store.currentSlide === Number(idx) ? 'var(--primary-dim)' : 'transparent',
                  border: store.currentSlide === Number(idx) ? '2px solid var(--primary)' : '2px solid transparent',
                  transition: 'all 0.2s',
                }}
              >
                <img
                  src={url}
                  alt={`Slide ${idx}`}
                  style={{ width: '100%', borderRadius: 4, display: 'block' }}
                />
                <Text style={{
                  display: 'block',
                  textAlign: 'center',
                  fontSize: 12,
                  marginTop: 4,
                  color: store.currentSlide === Number(idx) ? 'var(--primary)' : 'var(--text-gray)',
                  fontWeight: store.currentSlide === Number(idx) ? 700 : 400,
                }}>
                  第 {idx} 页
                </Text>
                {/* 状态指示 */}
                <div style={{ display: 'flex', justifyContent: 'center', gap: 4, marginTop: 2 }}>
                  {store.scripts[String(idx)] && <CheckCircleOutlined style={{ fontSize: 10, color: 'var(--success)' }} />}
                  {store.audioReady[String(idx)] && <SoundOutlined style={{ fontSize: 10, color: 'var(--info)' }} />}
                  {store.srtReady[String(idx)] && <FileDoneOutlined style={{ fontSize: 10, color: 'var(--purple)' }} />}
                </div>
              </div>
            ))}
          </div>
        </Sider>

        {/* 中间：预览区 */}
        <Content style={{
          background: 'var(--bg-warm)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 16,
          position: 'relative',
        }}>
          {/* 导航箭头 */}
          {store.currentSlide > 1 && (
            <Button
              icon={<LeftOutlined />}
              style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', zIndex: 2, borderRadius: '50%' }}
              onClick={() => store.setCurrentSlide(store.currentSlide - 1)}
            />
          )}
          {store.currentSlide < store.slideCount && (
            <Button
              icon={<RightOutlined />}
              style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', zIndex: 2, borderRadius: '50%' }}
              onClick={() => store.setCurrentSlide(store.currentSlide + 1)}
            />
          )}

          {/* 幻灯片大图 */}
          {currentSlideUrl && (
            <img
              src={currentSlideUrl}
              alt={`Slide ${store.currentSlide}`}
              style={{
                maxWidth: '100%',
                maxHeight: 'calc(100% - 60px)',
                objectFit: 'contain',
                borderRadius: 8,
                boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                cursor: 'pointer',
              }}
              onClick={() => { setPreviewImage(currentSlideUrl); setPreviewVisible(true) }}
              className={store.smartartSlides?.includes(store.currentSlide) ? 'smartart-slide' : ''}
            />
          )}

          {/* 底部信息 */}
          <div style={{ marginTop: 12, textAlign: 'center' }}>
            <Text strong>第 {store.currentSlide} / {store.slideCount} 页</Text>
            <Tooltip title="全屏查看">
              <Button
                type="text"
                icon={<ExpandOutlined />}
                size="small"
                onClick={() => { setPreviewImage(currentSlideUrl); setPreviewVisible(true) }}
                style={{ marginLeft: 8 }}
              />
            </Tooltip>
            <Upload
              accept=".png,.jpg,.jpeg"
              showUploadList={false}
              customRequest={({ file }) => handleReplaceImage(store.currentSlide, file)}
              style={{ display: 'inline' }}
            >
              <Button icon={<UploadOutlined />} size="small" type="dashed" style={{ marginLeft: 8 }}>
                替换图片
              </Button>
            </Upload>
          </div>
        </Content>

        {/* 右侧：编辑与生成面板 */}
        <Sider
          width={360}
          style={{
            background: 'var(--bg-panel)',
            borderRadius: '0 16px 16px 0',
            overflow: 'auto',
            borderLeft: '1px solid var(--border)',
          }}
        >
          <div style={{ padding: 16 }}>
            {/* 解说词编辑区 */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <Title level={5} style={{ margin: 0 }}>
                  <FileTextOutlined /> 解说词
                </Title>
                <Text type="secondary" style={{ fontSize: 12 }}>第 {store.currentSlide} 页</Text>
              </div>

              {editingSlide === store.currentSlide ? (
                <TextArea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onBlur={finishEdit}
                  autoSize={{ minRows: 6, maxRows: 14 }}
                  style={{ borderRadius: 8, borderColor: 'var(--primary)' }}
                  autoFocus
                />
              ) : (
                <div
                  onDoubleClick={() => startEdit(store.currentSlide)}
                  style={{
                    padding: '12px',
                    background: 'var(--bg-elevated)',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    minHeight: 100,
                    cursor: 'text',
                    whiteSpace: 'pre-wrap',
                    fontSize: 14,
                    lineHeight: 1.8,
                    color: currentScript ? 'var(--text-dark)' : 'var(--text-light)',
                  }}
                >
                  {currentScript || '双击此处编辑解说词，或点击"生成当前页解说词"按钮'}
                </div>
              )}

              <Space style={{ marginTop: 8 }} wrap>
                <Button
                  type="primary"
                  size="small"
                  icon={<RocketOutlined />}
                  loading={store.generatingScript}
                  onClick={() => handleGenerateScript(store.currentSlide)}
                >
                  生成当前页解说词
                </Button>
                {store.slideCount > 10 && (
                  <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>
                    💡 共 {store.slideCount} 页，建议使用下方"全部生成解说词"异步批量处理
                  </Text>
                )}
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => startEdit(store.currentSlide)}
                >
                  编辑
                </Button>
              </Space>
            </div>

            {/* 全局操作 */}
            <div style={{
              padding: '12px',
              background: 'var(--primary-dim)',
              borderRadius: 12,
              marginBottom: 20,
              border: '1px solid var(--primary-border)',
            }}>
              <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13 }}>批量操作</Text>
              <Space wrap>
                <Button
                  size="small"
                  type="primary"
                  onClick={handleAsyncGenerateAll}
                >
                  全部生成解说词
                </Button>
              </Space>

              {/* 异步任务进度 */}
              {store.asyncTaskId && store.asyncTaskStatus === 'processing' && (
                <div style={{ marginTop: 12 }}>
                  <Progress
                    percent={store.asyncTaskProgress}
                    size="small"
                    status="active"
                  />
                  <Text type="secondary" style={{ fontSize: 12 }}>{store.asyncTaskMessage}</Text>
                </div>
              )}
            </div>

            {/* 设置区 */}
            <div style={{ marginBottom: 20 }}>
              <Title level={5} style={{ marginBottom: 12 }}>
                <SoundOutlined /> 生成设置
              </Title>
              <div style={{ marginBottom: 8 }}>
                <Text style={{ fontSize: 13, display: 'block', marginBottom: 4 }}>音色</Text>
                <Select
                  value={selectedVoice}
                  onChange={setSelectedVoice}
                  options={voices.length > 0 ? voices : VOICE_OPTIONS}
                  style={{ width: '100%' }}
                  size="small"
                />
              </div>
              <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text style={{ fontSize: 13 }}>字幕</Text>
                <Switch
                  checked={store.subtitleEnabled}
                  onChange={store.setSubtitleEnabled}
                  size="small"
                  checkedChildren="开"
                  unCheckedChildren="关"
                />
              </div>
            </div>

            {/* 步骤式生成 */}
            <div>
              <Title level={5} style={{ marginBottom: 12 }}>
                <VideoCameraOutlined /> 生成流水线
              </Title>
              <Steps
                direction="vertical"
                size="small"
                current={-1}
                items={[
                  {
                    title: '解说词',
                    description: currentScript ? '已生成' : '未生成',
                    status: currentScript ? 'finish' : 'wait',
                    icon: <FileTextOutlined />,
                  },
                  {
                    title: '音频',
                    description: store.audioReady[String(store.currentSlide)] ? '已合成' : '未合成',
                    status: store.audioReady[String(store.currentSlide)] ? 'finish' : 'wait',
                    icon: <SoundOutlined />,
                  },
                  {
                    title: '字幕',
                    description: store.srtReady[String(store.currentSlide)] ? '已生成' : '未生成',
                    status: store.srtReady[String(store.currentSlide)] ? 'finish' : 'wait',
                    icon: <FileDoneOutlined />,
                  },
                  {
                    title: '视频',
                    description: store.videoUrl ? '已完成' : '未生成',
                    status: store.videoUrl ? 'finish' : 'wait',
                    icon: <VideoCameraOutlined />,
                  },
                ]}
              />

              <Space direction="vertical" style={{ width: '100%', marginTop: 12 }} size={8}>
                <Button
                  block
                  size="middle"
                  icon={<SoundFilled />}
                  loading={store.generatingAudio || store.generatingSrt}
                  disabled={!Object.values(store.scripts).some(Boolean)}
                  onClick={handleGenerateAllAudioAndSrt}
                >
                  {store.generatingAudio ? '生成音频中...' : store.generatingSrt ? '生成字幕中...' : '一键生成全部音频+字幕'}
                </Button>
                <Button
                  block
                  type="primary"
                  className="btn-gradient"
                  icon={<VideoCameraOutlined />}
                  loading={store.generatingVideo}
                  onClick={handleGenerateVideo}
                  style={{ borderRadius: 8, height: 42, fontWeight: 600 }}
                >
                  合成最终视频
                </Button>
              </Space>

              {/* 视频结果 */}
              {store.videoUrl && (
                <div style={{ marginTop: 16 }}>
                  <Text strong style={{ color: 'var(--success)', display: 'block', marginBottom: 8 }}>
                    <CheckCircleOutlined /> 视频已就绪
                  </Text>
                  {/* 内嵌视频播放器 */}
                  <video
                    controls
                    style={{
                      width: '100%',
                      borderRadius: 8,
                      background: '#000',
                      marginBottom: 8,
                    }}
                    src={store.videoUrl}
                  >
                    您的浏览器不支持视频播放
                  </video>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Button
                      type="primary"
                      size="small"
                      icon={<DownloadOutlined />}
                      onClick={() => {
                        const a = document.createElement('a')
                        a.href = store.videoUrl
                        a.download = 'output.mp4'
                        a.click()
                      }}
                    >
                      另存为
                    </Button>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={handleBackToEdit}
                    >
                      返回修改解说词
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* 重新上传 */}
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
              <Upload
                accept=".pptx,.ppt"
                showUploadList={false}
                beforeUpload={handleUpload}
                disabled={uploading}
              >
                <Button block size="small" icon={<UploadOutlined />} loading={uploading}>
                  重新上传 PPT
                </Button>
              </Upload>
            </div>
          </div>
        </Sider>
      </Layout>

      {/* 大图预览 Modal */}
      <Modal
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={null}
        width="90vw"
        style={{ top: 20 }}
        styles={{ body: { padding: 0, textAlign: 'center' } }}
      >
        <img src={previewImage} alt="Preview" style={{ maxWidth: '100%', maxHeight: '85vh' }} />
      </Modal>
    </div>
  )
}

/* ───────────── 顶部导航 ───────────── */
function StudioHeader({ navigate, hasJob }) {
  return (
    <header className="app-header" style={{ padding: '10px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => navigate('/')}>
        <div className="brand-mark">P</div>
        <Title level={4} style={{ margin: 0, color: 'var(--text-dark)', letterSpacing: 0.3 }}>PPT2Video</Title>
      </div>
      <Space>
        {hasJob && (
          <Button icon={<HomeOutlined />} size="small" ghost onClick={() => navigate('/')}>首页</Button>
        )}
        <Button icon={<HistoryOutlined />} size="small" ghost onClick={() => navigate('/history')}>历史记录</Button>
      </Space>
    </header>
  )
}
