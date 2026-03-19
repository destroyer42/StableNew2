List of things that are still not working:

2. Make the preview of the prompt pack persist when clicking into it (so you can highlight text and copy)
3. In Core config Steps and CFG spin boxes still aren't dark mode
4. Dropdowns for everything still have light mode for the dropdowns list in Core config
5. Enable Adetailer should default to enabled
6. Output Dir is not modifiable and doesn't contain an actual pathname
7. Filename is not modifiable and doesn't indicate what options are (should have a hover over explaining 
how to use tokens to indicate things the program understands
8. What is batch size vs batch runs? unclear. 
9. What functionality does seed mode have, and when is it incorporated?
10. Restore last run (expected behavior is that last run automatically populates when starting up program. If
configs or options are changed, and restore last run is pressed before another job runs, then the last job run configs would replace whatever options/configs are currently selected. 
11. Needs to be a config override checkbox in the middle panel (top) that would allow for the current stage config to override the prompt packs config (without the need to overwrite the prompt packs config) so you could do one off experiments without losing the packs current config.
12. When window first opens it is too narrow (cuts off right panel) (resizing doesn't work right)
13. Randomize button on seeds doesn't do anything
14. SDXL Refiner label in light mode still
15. Enable refiner checkbox should show/hide refiner options
17. Same issue with hires fix checkbox (needs to hide/show hires fix options)
19. Hires fix needs to have a model selector if the user doesn't want to use the base model (which would then make the "Use base model during hires" redundant, because it would default to the base model, but the user could change it to whatever they want
20. Scroll bars should work anywhere in the section you have your mouse on and only if clicking into a widget/control should the focus of the scroll function be on that things options to change.
22. Final size calculation on upscale seems broken (says 0x0 regardless of selections)
24. Preview needs to show more information, like positive prompt, negative prompt, a chart of the settings that are getting passed in,
25. Need to simplify the run controls 
	- "Add to queue" takes whatever prompt packs have been added to the job preview and adds them to the queue (Queue should look more like Job history with one of the columns being order number. so as jobs get added to the queue, the job gets added to the bottom of the list and get assigned an order number. 
	-  "Clear Draft" erases preview and the added jobs that haven't been added to the queue yet (top of preview section)
	- Mode - needs to be removed, unclear what direct vs queue means. Should manage all jobs through the queue
	- Checkbox for Queue to auto run (as soon as any job is queued, pipeline will automatically start, and will continue on until all jobs have finished.
	- Pause and Resume need to be one button/toggle (name changes between run/pause depending on state of button)
	- Queued jobs should be selectable (like in a list) and when a single job is selected should have options to move job up and down the queue (up and down arrows), and remove that particular job from queue
	- Queue card should have a button to "Clear Queue" that removes all queued jobs from queue
	- Clear draft - no change, good as is (just should be sitting underneath preview, and should have a frame/card around it and rest of preview section
	- Queue section should have frame around it, with lines and number as the first category
	- Running job - should be its own card and have pause job/resume job button/toggle and cancel and trash job, and cancel and return job to queue (goes to bottom of list)
	- Progress indicator and running timer on current job with E.T.A
	- Queue should persist between program exits, jobs should auto-resume if connection is lost then regained
	* Technically all states should persist and resume between exits and start of program
26. Details button should default to showing terminal with logging
28. Right panel in pipeline tab needs to be embedded/nested in scrollable frame
	