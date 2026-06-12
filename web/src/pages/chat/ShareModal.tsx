import { useEffect, useState } from 'react'
import { Button, Input, Modal, Select, Space, message } from 'antd'
import { CopyOutlined, LinkOutlined } from '@ant-design/icons'
import { shareApi, type Share } from '@/api/shares'
import { copyText } from '@/utils/clipboard'

interface Props {
  open: boolean
  conversationId?: string
  onClose: () => void
}

// 对话分享弹窗：生成只读链接 + 复制 + 选过期 + 取消分享。
export default function ShareModal({ open, conversationId, onClose }: Props) {
  const [share, setShare] = useState<Share | null>(null)
  const [expireDays, setExpireDays] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) {
      setShare(null)
      setExpireDays(null)
    }
  }, [open, conversationId])

  const link = share ? `${window.location.origin}/s/${share.share_token}` : ''

  const onGenerate = async () => {
    if (!conversationId) {
      message.warning('请先选择一个会话')
      return
    }
    setLoading(true)
    try {
      const { data } = await shareApi.create(conversationId, expireDays)
      setShare(data)
      message.success('已生成分享链接')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const onCopy = async () => {
    const ok = await copyText(link)
    if (ok) message.success('链接已复制')
    else message.error('复制失败')
  }

  const onRevoke = async () => {
    if (!share) return
    try {
      await shareApi.revoke(share.id)
      message.success('已取消分享，链接失效')
      setShare(null)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="分享对话"
      width={520}
    >
      <p style={{ color: '#667085', fontSize: 13, marginTop: 4 }}>
        生成只读分享链接，他人无需登录即可查看。分享为快照，之后继续聊不影响已分享内容。
      </p>
      {!share ? (
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, color: '#344054' }}>有效期</span>
            <Select
              value={expireDays}
              onChange={setExpireDays}
              style={{ width: 160 }}
              options={[
                { value: null, label: '永久有效' },
                { value: 7, label: '7 天后过期' },
                { value: 30, label: '30 天后过期' },
              ]}
            />
          </div>
          <Button
            type="primary"
            icon={<LinkOutlined />}
            loading={loading}
            onClick={onGenerate}
            block
          >
            生成分享链接
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={link} readOnly />
            <Button type="primary" icon={<CopyOutlined />} onClick={onCopy}>
              复制
            </Button>
          </Space.Compact>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: '#98A2B3' }}>
              {share.expire_at ? `将于 ${new Date(share.expire_at).toLocaleDateString()} 过期` : '永久有效'}
            </span>
            <Button type="text" danger size="small" onClick={onRevoke}>
              取消分享
            </Button>
          </div>
        </Space>
      )}
    </Modal>
  )
}
