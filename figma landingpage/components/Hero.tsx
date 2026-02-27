import { Calendar, Upload } from 'lucide-react';
import { motion } from 'motion/react';

export function Hero() {
  const scrollToUpload = () => {
    document.getElementById('upload-section')?.scrollIntoView({ behavior: 'smooth' });
  };

  // Calendar events that will animate in
  const calendarEvents = [
    { day: 2, label: 'Lecture 1', delay: 0 },
    { day: 4, label: 'Assignment 1', delay: 0.3 },
    { day: 9, label: 'Lab 1', delay: 0.6 },
    { day: 11, label: 'Lecture 2', delay: 0.9 },
    { day: 16, label: 'Assignment 2', delay: 1.2 },
    { day: 18, label: 'Lab 2', delay: 1.5 },
    { day: 23, label: 'Midterm', delay: 1.8 },
    { day: 25, label: 'Lecture 3', delay: 2.1 },
  ];

  return (
    <section className="relative px-6 py-24 md:py-32 overflow-hidden">
      {/* Background Calendar Animation */}
      <div className="absolute inset-0 flex items-center justify-center px-6 opacity-30">
        <div className="w-full max-w-7xl">
          {/* Calendar Grid */}
          <div className="grid grid-cols-7 gap-3">
            {Array.from({ length: 35 }).map((_, index) => {
              const dayNum = index + 1;
              const event = calendarEvents.find(e => e.day === dayNum);
              
              return (
                <div key={index} className="relative aspect-square">
                  <div className="h-full rounded border border-blue-500/40 bg-blue-500/10 p-2">
                    <div className="text-sm text-blue-300">{dayNum}</div>
                    {event && (
                      <motion.div
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: [0, 1, 1, 1, 0], scale: [0.8, 1, 1, 1, 0.8] }}
                        transition={{
                          duration: 5,
                          delay: event.delay,
                          repeat: Infinity,
                          repeatDelay: 3,
                          ease: "easeOut"
                        }}
                        className="mt-1 rounded bg-blue-500 px-1 py-0.5 text-xs leading-tight text-white"
                      >
                        {event.label}
                      </motion.div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-4xl text-center relative z-10">
        {/* Content Card with backdrop */}
        <div className="rounded-3xl border border-zinc-800 bg-zinc-950/90 backdrop-blur-sm p-12 shadow-2xl">
          <div className="mb-8 inline-flex items-center gap-3 rounded-full border border-blue-500/20 bg-blue-500/10 px-4 py-2">
            <Calendar className="h-5 w-5 text-blue-400" />
            <span className="text-sm text-blue-300">Automatic Course Calendar Generation</span>
          </div>
          
          <h1 className="mb-6 text-5xl md:text-7xl tracking-tight">
            From Course Outline to Calendar in Seconds
          </h1>
          
          <p className="mx-auto mb-12 max-w-2xl text-xl text-zinc-400">
            Upload your course outline and instantly generate a calendar file with all assignments, 
            lectures, labs, and due dates automatically extracted.
          </p>
          
          <button 
            onClick={scrollToUpload}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-8 py-4 transition-colors hover:bg-blue-500"
          >
            <Upload className="h-5 w-5" />
            Get Started
          </button>
        </div>
      </div>
      
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 h-96 w-96 -translate-x-1/2 rounded-full bg-blue-500/20 blur-3xl" />
      </div>
    </section>
  );
}