import { create } from 'zustand'
import { musicApi, type Recommendation, type Song } from '@/api/music'

// 播放器当前曲目（推荐结果或曲库歌曲统一成这个结构）
export interface PlayerTrack {
  id: string | null
  title: string
  artist: string
  url: string | null // 可播放音频地址；为 null 但 playable=true 时播放前现取
  playable: boolean
  coverUrl: string | null
  lyric: string | null
  valence?: number
  arousal?: number
  reason?: string
  sourceLayer?: string
}

interface MusicState {
  playlist: PlayerTrack[]
  index: number
  track: PlayerTrack | null
  visible: boolean
  expanded: boolean
  playing: boolean
  loading: boolean
  resolving: boolean // 正在现取音源
  recommendReason: string // 「为我推荐」的推荐语（整个推荐队列共用）
  setPlaying: (v: boolean) => void
  setExpanded: (v: boolean) => void
  close: () => void
  playList: (songs: Song[], startIndex: number) => void
  next: () => void
  prev: () => void
  recommend: () => Promise<void>
}

function songToTrack(song: Song): PlayerTrack {
  return {
    id: song.id,
    title: song.title,
    artist: song.artist,
    url: song.url,
    playable: song.playable,
    coverUrl: song.cover_url,
    lyric: song.lyric,
    valence: song.valence,
    arousal: song.arousal,
    sourceLayer: song.file_key ? 'local' : song.source_url ? 'manual' : 'migu_free',
  }
}

function recToTrack(rec: Recommendation): PlayerTrack {
  const url = rec.url ?? rec.source_url ?? null
  return {
    id: rec.id,
    title: rec.title ?? '未知歌曲',
    artist: rec.artist ?? '',
    url,
    playable: rec.playable ?? !!url,
    coverUrl: rec.cover_url ?? null,
    lyric: rec.lyric ?? null,
    valence: rec.valence,
    arousal: rec.arousal,
    reason: rec.reason,
    sourceLayer: rec.source_layer,
  }
}

// 解析某首曲目的真实音源直链：返回更新后的 track 与是否可播
async function resolveTrack(t: PlayerTrack): Promise<PlayerTrack> {
  if (t.url || !t.id) return t
  try {
    const { data } = await musicApi.resolveAudio(t.id)
    if (data.url) {
      return { ...t, url: data.url, playable: true, sourceLayer: data.source_layer }
    }
    return { ...t, playable: false, sourceLayer: 'display_only' }
  } catch {
    return { ...t, playable: false }
  }
}

export const useMusicStore = create<MusicState>((set, get) => {
  // 从 startIndex 朝 dir 方向找到第一首能播的歌（现取验证），最多遍历整个队列
  const playFrom = async (startIndex: number, dir: 1 | -1) => {
    const { playlist } = get()
    const n = playlist.length
    if (n === 0) return
    for (let step = 0; step < n; step++) {
      const idx = ((startIndex + dir * step) % n + n) % n
      const base = playlist[idx]
      // 先切到该首（展示），标记取源中
      set({ index: idx, track: base, playing: false, resolving: true })
      const resolved = await resolveTrack(base)
      // 解析期间用户可能又切了歌：确认仍停在这首再处理
      if (get().index !== idx) return
      // 把解析结果写回队列与当前
      const list = [...get().playlist]
      list[idx] = resolved
      if (resolved.playable && resolved.url) {
        set({ playlist: list, track: resolved, playing: true, resolving: false })
        return
      }
      // 这首没音源，继续找下一首；最后一轮则停在这并提示无音源
      set({ playlist: list, track: resolved })
    }
    // 整个队列都没有可播的
    set({ playing: false, resolving: false })
  }

  return {
    playlist: [],
    index: -1,
    track: null,
    visible: false,
    expanded: false,
    playing: false,
    loading: false,
    resolving: false,
    recommendReason: '',

    setPlaying: (v) => set({ playing: v }),
    setExpanded: (v) => set({ expanded: v }),
    close: () => set({ visible: false, playing: false }),

    playList: (songs, startIndex) => {
      const list = songs.map(songToTrack)
      const idx = Math.max(0, Math.min(startIndex, list.length - 1))
      // 曲库手动播放，清空推荐语
      set({ playlist: list, visible: true, recommendReason: '' })
      void playFrom(idx, 1)
    },

    next: () => {
      const { playlist, index } = get()
      if (playlist.length === 0) return
      void playFrom(index + 1, 1)
    },

    prev: () => {
      const { playlist, index } = get()
      if (playlist.length === 0) return
      void playFrom(index - 1, -1)
    },

    recommend: async () => {
      set({ loading: true, visible: true })
      try {
        const { data } = await musicApi.recommend()
        const list = (data.items ?? []).map(recToTrack)
        if (list.length === 0) return
        set({ playlist: list, index: -1, recommendReason: data.reason || '' })
        await playFrom(0, 1)
      } finally {
        set({ loading: false })
      }
    },
  }
})
