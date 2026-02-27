import { motion } from 'motion/react';
import { FileText, Zap, Calendar } from 'lucide-react';

export function HowItWorks() {
  const features = [
    {
      icon: FileText,
      title: 'Upload Course Outline',
      description: 'Support for PDF, DOCX, and TXT formats'
    },
    {
      icon: Zap,
      title: 'Automatic Extraction',
      description: 'AI-powered parsing of assignments, lectures, and labs'
    },
    {
      icon: Calendar,
      title: 'Calendar Export',
      description: 'Download .ics file compatible with all calendar apps'
    }
  ];

  const cycleDuration = 7; // Total duration of one complete animation cycle

  return (
    <section className="border-t border-zinc-800 px-6 py-24 bg-zinc-900/50">
      <div className="mx-auto max-w-4xl">
        <h2 className="mb-16 text-center text-4xl">How It Works</h2>
        
        {/* Animated Workflow Visualization */}
        <div className="mb-20 flex items-center justify-center gap-8">
          {/* Document Icon */}
          <motion.div
            className="flex flex-col items-center gap-2"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: [0, 1, 1, 1, 1, 1, 1, 0], x: [-20, 0, 0, 0, 0, 0, 0, -20] }}
            transition={{ 
              duration: cycleDuration,
              times: [0, 0.11, 0.4, 0.5, 0.6, 0.7, 0.85, 1],
              repeat: Infinity,
              ease: "easeOut"
            }}
          >
            <div className="flex h-20 w-20 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10">
              <FileText className="h-10 w-10 text-blue-400" />
            </div>
            <span className="text-xs text-zinc-500">Course Outline</span>
          </motion.div>

          {/* Arrow 1 with particle */}
          <div className="relative">
            <motion.div
              className="h-0.5 w-24 bg-gradient-to-r from-blue-500 to-transparent"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: [0, 0, 1, 1, 1, 1, 1, 0] }}
              transition={{ 
                duration: cycleDuration,
                times: [0, 0.11, 0.23, 0.4, 0.5, 0.6, 0.85, 1],
                repeat: Infinity,
                ease: "easeOut"
              }}
              style={{ originX: 0 }}
            />
            <motion.div
              className="absolute left-0 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-blue-400"
              initial={{ x: 0, opacity: 0 }}
              animate={{ 
                x: [0, 0, 96, 96, 96, 96, 96, 0],
                opacity: [0, 0, 1, 1, 1, 1, 0, 0]
              }}
              transition={{ 
                duration: cycleDuration,
                times: [0, 0.11, 0.23, 0.4, 0.5, 0.6, 0.85, 1],
                repeat: Infinity,
                ease: "easeOut"
              }}
            />
          </div>

          {/* Processing Icon */}
          <motion.div
            className="flex flex-col items-center gap-2"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ 
              opacity: [0, 0, 0, 1, 1, 1, 1, 0],
              scale: [0.8, 0.8, 0.8, 1, 1, 1, 1, 0.8]
            }}
            transition={{ 
              duration: cycleDuration,
              times: [0, 0.11, 0.23, 0.3, 0.5, 0.6, 0.85, 1],
              repeat: Infinity,
              ease: "easeOut"
            }}
          >
            <div className="relative flex h-20 w-20 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10">
              <motion.div
                animate={{ rotate: [0, 0, 0, 360, 720, 720, 720, 0] }}
                transition={{ 
                  duration: cycleDuration,
                  times: [0, 0.11, 0.23, 0.44, 0.6, 0.7, 0.85, 1],
                  repeat: Infinity,
                  ease: "linear"
                }}
              >
                <Zap className="h-10 w-10 text-blue-400" />
              </motion.div>
              <motion.div
                className="absolute inset-0 rounded-lg border border-blue-500"
                animate={{ opacity: [0, 0, 0, 0.5, 0, 0.5, 0, 0] }}
                transition={{ 
                  duration: cycleDuration,
                  times: [0, 0.11, 0.23, 0.37, 0.44, 0.52, 0.6, 1],
                  repeat: Infinity
                }}
              />
            </div>
            <span className="text-xs text-zinc-500">Processing</span>
          </motion.div>

          {/* Arrow 2 with particle */}
          <div className="relative">
            <motion.div
              className="h-0.5 w-24 bg-gradient-to-r from-blue-500 to-transparent"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: [0, 0, 0, 0, 0, 1, 1, 0] }}
              transition={{ 
                duration: cycleDuration,
                times: [0, 0.23, 0.37, 0.44, 0.52, 0.63, 0.85, 1],
                repeat: Infinity,
                ease: "easeOut"
              }}
              style={{ originX: 0 }}
            />
            <motion.div
              className="absolute left-0 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-blue-400"
              initial={{ x: 0, opacity: 0 }}
              animate={{ 
                x: [0, 0, 0, 0, 0, 96, 96, 0],
                opacity: [0, 0, 0, 0, 0, 1, 0, 0]
              }}
              transition={{ 
                duration: cycleDuration,
                times: [0, 0.23, 0.37, 0.44, 0.52, 0.63, 0.85, 1],
                repeat: Infinity,
                ease: "easeOut"
              }}
            />
          </div>

          {/* Calendar Icon */}
          <motion.div
            className="flex flex-col items-center gap-2"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: [0, 0, 0, 0, 0, 0, 1, 0], x: [20, 20, 20, 20, 20, 20, 0, 20] }}
            transition={{ 
              duration: cycleDuration,
              times: [0, 0.23, 0.37, 0.44, 0.52, 0.63, 0.74, 1],
              repeat: Infinity,
              ease: "easeOut"
            }}
          >
            <div className="flex h-20 w-20 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10">
              <Calendar className="h-10 w-10 text-blue-400" />
            </div>
            <span className="text-xs text-zinc-500">Calendar File</span>
          </motion.div>
        </div>
        
        <div className="mx-auto max-w-6xl">
          <div className="grid gap-12 md:grid-cols-3">
            {features.map((feature, index) => (
              <div key={index} className="text-center">
                <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-blue-500/10 border border-blue-500/20">
                  <feature.icon className="h-6 w-6 text-blue-400" />
                </div>
                <h3 className="mb-2">{feature.title}</h3>
                <p className="text-zinc-400">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}