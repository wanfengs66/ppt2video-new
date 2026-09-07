import { create } from 'zustand'

const useStudioStore = create((set, get) => ({
  // PPT 上传状态
  uploading: false,
  uploadProgress: 0,

  // 当前任务
  filePath: '',       // job_id (UUID)
  slides: {},         // { "1": "path/to/slide_1.png", ... }
  slideCount: 0,
  smartartSlides: [], // 包含 SmartArt 的页码

  // 当前选中的幻灯片
  currentSlide: 1,

  // 解说词
  scripts: {},        // { "1": "解说词文本", ... }
  generatingScript: false,
  generatingAll: false,

  // 音频/字幕/视频
  audioReady: {},     // { "1": true/false }
  srtReady: {},
  generatingAudio: false,
  generatingSrt: false,
  generatingVideo: false,
  videoUrl: '',

  // 异步任务
  asyncTaskId: '',
  asyncTaskStatus: '',
  asyncTaskProgress: 0,
  asyncTaskMessage: '',

  // 字幕开关
  subtitleEnabled: false,
  setSubtitleEnabled: (v) => set({ subtitleEnabled: v }),

  // 音色选择
  voiceType: 'male',

  // 理解级别
  understandingLevel: 'text-understanding',

  // ── Actions ──
  setUploadState: (uploading, progress = 0) => set({ uploading, uploadProgress: progress }),

  setJobData: ({ filePath, ossUrls, smartartSlides }) => {
    const slideCount = Object.keys(ossUrls).length
    set({
      filePath,
      slides: ossUrls,
      slideCount,
      smartartSlides: smartartSlides || [],
      currentSlide: 1,
      scripts: {},
      audioReady: {},
      srtReady: {},
      videoUrl: '',
    })
  },

  setSlides: (slides) => set({ slides }),

  setCurrentSlide: (slide) => set({ currentSlide: slide }),

  setScript: (slideIndex, text) => set((state) => ({
    scripts: { ...state.scripts, [String(slideIndex)]: text },
  })),

  setAllScripts: (scripts) => {
    const scriptMap = {}
    scripts.forEach((s, i) => {
      // 尝试从 slide_index / index / image_url 中提取页码
      let idx = s.slide_index || s.index
      if (!idx && s.image_url) {
        const match = String(s.image_url).match(/slide_(\d+)/)
        if (match) idx = parseInt(match[1])
      }
      if (!idx) idx = i + 1
      scriptMap[String(idx)] = s.text
    })
    set({ scripts: scriptMap })
  },

  setAudioReady: (slideIndex, ready = true) => set((state) => ({
    audioReady: { ...state.audioReady, [String(slideIndex)]: ready },
  })),

  setSrtReady: (slideIndex, ready = true) => set((state) => ({
    srtReady: { ...state.srtReady, [String(slideIndex)]: ready },
  })),

  setVideoUrl: (url) => set({ videoUrl: url }),

  setGeneratingScript: (v) => set({ generatingScript: v }),
  setGeneratingAll: (v) => set({ generatingAll: v }),
  setGeneratingAudio: (v) => set({ generatingAudio: v }),
  setGeneratingSrt: (v) => set({ generatingSrt: v }),
  setGeneratingVideo: (v) => set({ generatingVideo: v }),

  setAsyncTask: (taskId, status, progress, message) => set({
    asyncTaskId: taskId,
    asyncTaskStatus: status,
    asyncTaskProgress: progress,
    asyncTaskMessage: message,
  }),

  reset: () => set({
    filePath: '',
    slides: {},
    slideCount: 0,
    smartartSlides: [],
    currentSlide: 1,
    scripts: {},
    audioReady: {},
    srtReady: {},
    videoUrl: '',
    asyncTaskId: '',
    asyncTaskStatus: '',
    asyncTaskProgress: 0,
    asyncTaskMessage: '',
  }),
}))

export default useStudioStore
