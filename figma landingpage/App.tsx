import { Hero } from './components/Hero';
import { HowItWorks } from './components/HowItWorks';
import { UploadSection } from './components/UploadSection';

export default function App() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Hero />
      <HowItWorks />
      <UploadSection />
    </div>
  );
}