import * as React from "react";
import { useNavigate } from "react-router-dom";
import { FolderGit2, PlayCircle, Settings } from "lucide-react";
import { useProjects } from "../../hooks/use-projects";
import { useRuns } from "../../hooks/use-runs";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "../../components/ui/command";

export function CommandPalette() {
  const [open, setOpen] = React.useState(false);
  const navigate = useNavigate();

  const { data: projects } = useProjects({ per_page: 5 });
  const { data: runs } = useRuns({ per_page: 5 });

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const runCommand = React.useCallback((command: () => unknown) => {
    setOpen(false);
    command();
  }, []);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Type a command or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        
        {projects && projects.data.length > 0 && (
          <CommandGroup heading="Projects">
            {projects.data.map((project) => (
              <CommandItem
                key={project.id}
                onSelect={() => runCommand(() => navigate(`/projects/${project.id}`))}
              >
                <FolderGit2 className="mr-2 h-4 w-4" />
                <span>{project.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {runs && runs.data.length > 0 && (
          <CommandGroup heading="Recent Runs">
            {runs.data.map((run) => (
              <CommandItem
                key={run.id}
                onSelect={() => runCommand(() => navigate(`/runs/${run.id}`))}
              >
                <PlayCircle className="mr-2 h-4 w-4" />
                <span>{run.pipeline_name}</span>
                <span className="ml-2 text-xs text-ink-subtle">({run.branch})</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        <CommandGroup heading="Settings">
          <CommandItem onSelect={() => runCommand(() => navigate('/settings'))}>
            <Settings className="mr-2 h-4 w-4" />
            <span>Settings</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
