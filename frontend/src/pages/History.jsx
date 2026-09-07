import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Card, Typography, Statistic, Space,
  Popconfirm, message, Tag, Empty,
} from 'antd'
import {
  VideoCameraOutlined, HistoryOutlined, DeleteOutlined,
  EditOutlined, DownloadOutlined, HomeOutlined,
  FileTextOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { getHistory, getHistoryStats, deleteHistory } from '../api'

const { Title, Text } = Typography

export default function History() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState([])
  const [stats, setStats] = useState(null)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    fetchData()
    fetchStats()
  }, [])

  const fetchData = async (page = 1, pageSize = 20) => {
    setLoading(true)
    try {
      const res = await getHistory({ page, page_size: pageSize })
      const list = res.data.history || res.data || []
      setData(list)
      setPagination(prev => ({
        ...prev,
        current: page,
        pageSize,
        total: res.data.total || list.length,
      }))
    } catch {
      message.error('获取历史记录失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const res = await getHistoryStats()
      setStats(res.data)
    } catch {}
  }

  const handleDelete = async (jobId) => {
    try {
      await deleteHistory(jobId)
      message.success('已删除')
      setSelectedRowKeys(prev => prev.filter(id => id !== jobId))
      fetchData(pagination.current, pagination.pageSize)
      fetchStats()
    } catch {
      message.error('删除失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的记录')
      return
    }
    setDeleting(true)
    let successCount = 0
    let failCount = 0
    for (const jobId of selectedRowKeys) {
      try {
        await deleteHistory(jobId)
        successCount++
      } catch {
        failCount++
      }
    }
    setDeleting(false)
    setSelectedRowKeys([])
    if (failCount === 0) {
      message.success(`成功删除 ${successCount} 条记录`)
    } else {
      message.warning(`删除完成：${successCount} 成功，${failCount} 失败`)
    }
    fetchData(pagination.current, pagination.pageSize)
    fetchStats()
  }

  const columns = [
    {
      title: '任务 ID',
      dataIndex: 'job_id',
      key: 'job_id',
      width: 120,
      ellipsis: true,
      render: (id) => <Text copyable style={{ fontSize: 12 }}>{id?.slice(0, 8)}...</Text>,
    },
    {
      title: '文件名',
      dataIndex: 'original_filename',
      key: 'original_filename',
      ellipsis: true,
    },
    {
      title: '页数',
      dataIndex: 'slide_count',
      key: 'slide_count',
      width: 70,
      align: 'center',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => {
        const statusMap = {
          completed: { color: 'green', label: '已完成' },
          processing: { color: 'blue', label: '处理中' },
          failed: { color: 'red', label: '失败' },
          pending: { color: 'orange', label: '待处理' },
          expired: { color: '#999', label: '已过期' },
        }
        const info = statusMap[status] || { color: 'default', label: status || '未知' }
        return <Tag color={info.color}>{info.label}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, record) => (
        <Space size={[4, 2]} wrap>
          {record.status !== 'expired' && (
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => navigate(`/studio?job_id=${record.job_id}`)}
            >
              继续编辑
            </Button>
          )}
          {record.video_url && (
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              href={record.video_url}
              target="_blank"
            >
              下载
            </Button>
          )}
          <Popconfirm
            title="确定删除此记录？"
            onConfirm={() => handleDelete(record.job_id)}
            okText="删除"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-warm)', position: 'relative', overflow: 'hidden' }}>
      <div className="glow-orb" style={{ width: 420, height: 420, top: -140, right: '8%', background: 'rgba(74,181,224,0.1)' }} />
      {/* Header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => navigate('/')}>
          <div className="brand-mark">P</div>
          <Text strong style={{ fontSize: 18, letterSpacing: 0.3 }}>PPT2Video</Text>
        </div>
        <Space>
          <Button icon={<HomeOutlined />} ghost onClick={() => navigate('/')}>首页</Button>
          <Button type="primary" className="btn-gradient" icon={<EditOutlined />} onClick={() => navigate('/studio')} style={{ borderRadius: 999 }}>
            进入工作台
          </Button>
        </Space>
      </header>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 48px', position: 'relative' }}>
        <Title level={2} style={{ marginBottom: 24, color: 'var(--text-dark)' }}>
          <HistoryOutlined style={{ color: 'var(--primary-light)' }} /> 历史记录
        </Title>

        {/* 保留期限提醒 */}
        <div style={{
          padding: '10px 16px',
          marginBottom: 16,
          background: 'var(--primary-dim)',
          borderRadius: 10,
          border: '1px solid var(--primary-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <ClockCircleOutlined style={{ color: 'var(--primary-light)' }} />
          <Text style={{ fontSize: 13, color: 'var(--text-gray)' }}>
            任务记录仅保留 <Text strong style={{ color: 'var(--primary-light)' }}>7 天</Text>，过期后文件自动清理，无法继续编辑。视频文件不受影响，仍可下载。
          </Text>
        </div>

        {/* 统计卡片 */}
        {stats && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 16,
            marginBottom: 24,
          }}>
            {[
              { title: '总任务数', value: stats.total || 0, icon: <FileTextOutlined />, color: 'var(--paper)', bg: 'var(--primary-dim)', bd: 'var(--primary-border)' },
              { title: '已完成', value: stats.completed || 0, icon: <VideoCameraOutlined />, color: 'var(--success)', bg: 'rgba(125,219,160,0.1)', bd: 'rgba(125,219,160,0.28)' },
              { title: '处理中', value: stats.processing || 0, icon: <ClockCircleOutlined />, color: 'var(--info)', bg: 'rgba(74,181,224,0.1)', bd: 'rgba(74,181,224,0.28)' },
              { title: '总时长(分钟)', value: stats.total_minutes || 0, icon: <ClockCircleOutlined />, color: 'var(--purple)', bg: 'rgba(201,184,245,0.1)', bd: 'rgba(201,184,245,0.28)', precision: 1 },
            ].map((s) => (
              <div key={s.title} className="glass-card" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{
                  width: 42,
                  height: 42,
                  borderRadius: 11,
                  background: s.bg,
                  border: `1px solid ${s.bd}`,
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 19,
                  color: s.color,
                  flexShrink: 0,
                }}>
                  {s.icon}
                </div>
                <Statistic
                  title={<span style={{ color: 'var(--text-gray)', fontSize: 12 }}>{s.title}</span>}
                  value={s.value}
                  precision={s.precision}
                  valueStyle={{ color: 'var(--text-dark)', fontSize: 24, fontWeight: 700 }}
                />
              </div>
            ))}
          </div>
        )}

        {/* 数据表格 */}
        <Card style={{ borderRadius: 14, border: '1px solid var(--border)' }} styles={{ body: { padding: '16px 20px' } }}>
          {/* 批量操作栏 */}
          {selectedRowKeys.length > 0 && (
            <div style={{
              marginBottom: 16,
              padding: '8px 16px',
              background: 'var(--primary-dim)',
              border: '1px solid var(--primary-border)',
              borderRadius: 10,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <Text>已选择 <Text strong style={{ color: 'var(--primary-light)' }}>{selectedRowKeys.length}</Text> 项</Text>
              <Popconfirm
                title={`确定删除选中的 ${selectedRowKeys.length} 条记录？`}
                description="此操作不可恢复"
                onConfirm={handleBatchDelete}
                okText="确定删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  loading={deleting}
                >
                  批量删除
                </Button>
              </Popconfirm>
            </div>
          )}
          <Table
            columns={columns}
            dataSource={data}
            rowKey="job_id"
            loading={loading}
            rowSelection={{
              selectedRowKeys,
              onChange: (keys) => setSelectedRowKeys(keys),
            }}
            pagination={{
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: pagination.total,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (page, pageSize) => fetchData(page, pageSize),
            }}
            locale={{
              emptyText: <Empty description="暂无历史记录，去工作台创建一个吧" />,
            }}
          />
        </Card>
      </div>
    </div>
  )
}
