'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

interface Conversation {
  id: string;
  client_name: string | null;
  client_phone: string | null;
  status: string;
  last_msg_at: string | null;
  channel: string | null;
}

export default function InboxPage() {
  const router = useRouter();
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;

  useEffect(() => {
    if (!token) {
      router.push('/login');
      return;
    }

    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/conversations?status_filter=${filter}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(res => res.json())
      .then(d => setConvs(d.conversations || []))
      .catch(() => router.push('/login'))
      .finally(() => setLoading(false));
  }, [router, token, filter]);

  if (loading) return <div className="flex items-center justify-center min-h-screen">Загрузка...</div>;

  return (
    <div className="min-h-screen mobile-pb">
      <header className="bg-white border-b border-gray-200 px-4 py-3 mobile-px">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <h1 className="text-lg font-bold text-primary">Инбокс</h1>
          <Link href="/dashboard" className="text-sm text-gray-600">← Дашборд</Link>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-4 mobile-px">
        {/* Фильтры */}
        <div className="flex gap-2 mb-4 overflow-x-auto">
          {[
            { key: 'all', label: 'Все' },
            { key: 'new', label: 'Новые' },
            { key: 'bot', label: 'Бот' },
            { key: 'human', label: 'В работе' },
            { key: 'closed', label: 'Закрытые' },
          ].map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 rounded-full text-sm whitespace-nowrap ${
                filter === f.key
                  ? 'bg-primary text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Список диалогов */}
        {convs.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            Нет диалогов
          </div>
        ) : (
          <div className="space-y-2">
            {convs.map(c => (
              <Link
                key={c.id}
                href={`/inbox/${c.id}`}
                className="block p-4 bg-white rounded-xl border border-gray-200 hover:border-primary transition"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold">
                      {c.client_name || 'Аноним'}
                      {c.client_phone && <span className="text-sm text-gray-500 ml-2">{c.client_phone}</span>}
                    </div>
                    <div className="text-sm text-gray-500">
                      {c.channel === 'tg' ? '📱 Telegram' : c.channel === 'vk' ? '🔵 ВКонтакте' : '🌐 Виджет'}
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      c.status === 'new' ? 'bg-blue-100 text-blue-700' :
                      c.status === 'bot' ? 'bg-gray-100 text-gray-600' :
                      c.status === 'human' ? 'bg-amber-100 text-amber-700' :
                      'bg-green-100 text-green-700'
                    }`}>
                      {c.status}
                    </span>
                    {c.last_msg_at && (
                      <div className="text-xs text-gray-400 mt-1">
                        {new Date(c.last_msg_at).toLocaleString('ru-RU')}
                      </div>
                    )}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
