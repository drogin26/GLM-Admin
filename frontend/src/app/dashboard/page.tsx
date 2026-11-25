'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

interface DashboardData {
  total_conversations: number;
  bot_answered: number;
  human_handoff: number;
  lost_conversations: number;
  estimated_lost_revenue: number;
  avg_order_price: number;
}

export default function DashboardPage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;

  useEffect(() => {
    if (!token) {
      router.push('/login');
      return;
    }

    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/dashboard`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(res => {
        if (!res.ok) throw new Error('Unauthorized');
        return res.json();
      })
      .then(setData)
      .catch(() => router.push('/login'))
      .finally(() => setLoading(false));
  }, [router, token]);

  if (loading) {
    return <div className="flex items-center justify-center min-h-screen">Загрузка...</div>;
  }

  if (!data) return null;

  const formatRub = (v: number) =>
    new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(v);

  return (
    <div className="min-h-screen mobile-pb">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-4 py-3 mobile-px flex items-center justify-between">
        <h1 className="text-lg font-bold text-primary">AI-Администратор</h1>
        <nav className="flex gap-4 text-sm">
          <Link href="/inbox" className="text-gray-600 hover:text-primary">Инбокс</Link>
          <Link href="/knowledge" className="text-gray-600 hover:text-primary">Знания</Link>
          <Link href="/settings" className="text-gray-600 hover:text-primary">Настройки</Link>
        </nav>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6 mobile-px space-y-6">
        {/* Счётчики */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Диалогов" value={data.total_conversations} color="blue" />
          <MetricCard label="Ответил бот" value={data.bot_answered} color="green" />
          <MetricCard label="Передано человеку" value={data.human_handoff} color="amber" />
          <MetricCard label="Без ответа" value={data.lost_conversations} color="red" />
        </div>

        {/* Потерянные заявки — главный продающий артефакт */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-2xl">📊</span>
            <h2 className="text-xl font-bold">Потерянные заявки</h2>
          </div>

          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-gray-600">За прошлую неделю:</span>
              <span className="font-semibold">{data.lost_conversations}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Средний чек:</span>
              <span className="font-semibold">{formatRub(data.avg_order_price)}</span>
            </div>
            <div className="pt-3 border-t border-gray-100 flex justify-between">
              <span className="text-gray-600 font-medium">Оценка потерянной выручки:</span>
              <span className="text-xl font-bold text-danger">{formatRub(data.estimated_lost_revenue)}</span>
            </div>
          </div>

          <p className="text-xs text-gray-400 mt-4">
            Это те заявки, на которые клиент не получил ответ более 1 часа.
            С AI-Администратором таких не будет.
          </p>
        </div>

        {/* Быстрые действия */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <QuickAction
            title="Подключить Telegram"
            desc="Бот ответит за 30 секунд"
            href="/onboarding?step=telegram"
            icon="💬"
          />
          <QuickAction
            title="Подключить ВКонтакте"
            desc="Callback API для группы"
            href="/onboarding?step=vk"
            icon="🔵"
          />
          <QuickAction
            title="Установить виджет"
            desc="Вставьте скрипт на сайт"
            href="/onboarding?step=widget"
            icon="🌐"
          />
          <QuickAction
            title="Загрузить базу знаний"
            desc="Услуги, цены, условия"
            href="/knowledge"
            icon="📚"
          />
        </div>
      </main>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-green-50 text-green-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
  };

  return (
    <div className={`p-4 rounded-xl ${colorMap[color] || colorMap.blue}`}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-sm opacity-75">{label}</div>
    </div>
  );
}

function QuickAction({ title, desc, href, icon }: { title: string; desc: string; href: string; icon: string }) {
  return (
    <Link href={href} className="block p-4 bg-white rounded-xl border border-gray-200 hover:border-primary transition">
      <div className="text-2xl mb-2">{icon}</div>
      <div className="font-semibold">{title}</div>
      <div className="text-sm text-gray-500">{desc}</div>
    </Link>
  );
}
