/**
 * Client-side JavaScript for Course Outline to iCalendar Converter
 * 
 * This file contains JavaScript functions for enhancing the user experience
 * in the web interface. It handles form interactions, validation, and
 * dynamic content updates.
 */

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // Initialize form enhancements
    initFileUpload();
    initFormValidation();
    initDynamicForms();
    initEditableFields();
    initManualSectionAdders();
    initAssessmentAddRemove();
    
    // Re-enable form submission for the generate calendar button
    const generateBtn = document.getElementById('generate-calendar-btn');
    const reviewForm = document.getElementById('review-form');
    if (generateBtn && reviewForm) {
        generateBtn.addEventListener('click', function(e) {
            console.log('Generate Calendar button clicked');
            // Check if any field is currently being edited
            const editingField = document.querySelector('.editable-field.editing');
            if (editingField) {
                // Try to auto-save the field if it has a value
                const input = editingField.querySelector('.inline-edit-input');
                if (input) {
                    const fieldType = editingField.getAttribute('data-field-type');
                    const assessmentIndex = editingField.getAttribute('data-assessment-index');
                    const newValue = input.value.trim();
                    
                    // For date fields, allow saving even if empty (to clear the date)
                    if (newValue || fieldType === 'assessment_due_date' || fieldType === 'term_start' || fieldType === 'term_end') {
                        console.log('Auto-saving field before generating calendar');
                        // Get original content from a stored attribute or reconstruct
                        const originalContent = editingField.getAttribute('data-original-content') || editingField.textContent;
                        
                        // Save the field synchronously (we'll wait for it)
                        saveField(editingField, fieldType, newValue, assessmentIndex, originalContent);
                        
                        // Wait a moment for the save to complete, then submit
                        setTimeout(() => {
                            if (!document.querySelector('.editable-field.editing')) {
                                // Field is no longer in editing mode, safe to submit
                                reviewForm.onsubmit = function(e) {
                                    return true;
                                };
                                reviewForm.submit();
                            } else {
                                // Still editing, show alert
                                alert('Please wait for the field to finish saving, or cancel your edit before generating the calendar.');
                            }
                        }, 500);
                        e.preventDefault();
                        return false;
                    } else {
                        // No value entered, just cancel the edit
                        console.log('Cancelling edit with no value');
                        const originalContent = editingField.getAttribute('data-original-content') || '';
                        editingField.innerHTML = originalContent;
                        editingField.classList.remove('editing');
                        // Continue with form submission
                    }
                } else {
                    // Can't find input, show alert
                    e.preventDefault();
                    alert('Please refresh to save your changes.');
                    return false;
                }
            }
            
            // No fields being edited, proceed with submission
            reviewForm.onsubmit = function(e) {
                return true;
            };
            reviewForm.submit();
        });
    }
});

/**
 * Initialize file upload enhancements
 * Shows file name when file is selected
 */
function initFileUpload() {
    const fileInput = document.getElementById('pdf_file');
    const fileNameDisplay = document.getElementById('file-name');
    
    if (fileInput) {
        fileInput.addEventListener('change', function(e) {
            // Update file name display
            if (fileNameDisplay && this.files && this.files.length > 0) {
                const fileName = this.files[0].name;
                fileNameDisplay.textContent = fileName.length > 40 ? fileName.substring(0, 40) + '...' : fileName;
                fileNameDisplay.style.color = 'var(--color-success)';
                fileNameDisplay.style.fontStyle = 'normal';
            } else if (fileNameDisplay) {
                fileNameDisplay.textContent = 'No file selected';
                fileNameDisplay.style.color = 'var(--color-text-secondary)';
                fileNameDisplay.style.fontStyle = 'italic';
            }
        });
    }
}

/**
 * Initialize form validation
 * Provides client-side validation feedback
 */
function initFormValidation() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            // Basic validation - browser will handle required fields
            // Add custom validation here if needed
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('error');
                } else {
                    field.classList.remove('error');
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                alert('Please fill in all required fields.');
            }
        });
    });
}

/**
 * Initialize dynamic form elements
 * Handles show/hide logic for conditional form fields
 */
function initDynamicForms() {
    // Handle checkbox-triggered show/hide
    const checkboxes = document.querySelectorAll('input[type="checkbox"][data-toggle]');
    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const targetId = this.getAttribute('data-toggle');
            const target = document.getElementById(targetId);
            if (target) {
                target.style.display = this.checked ? 'block' : 'none';
            }
        });
    });
}

/**
 * Format date for display
 * Converts ISO date string to readable format
 * 
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date string
 */
function formatDate(dateString) {
    if (!dateString) return 'Not specified';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

/**
 * Format time for display
 * Converts time string to readable format
 * 
 * @param {string} timeString - Time string (HH:MM)
 * @returns {string} Formatted time string
 */
function formatTime(timeString) {
    if (!timeString) return 'Not specified';
    const [hours, minutes] = timeString.split(':');
    const hour = parseInt(hours);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const displayHour = hour % 12 || 12;
    return `${displayHour}:${minutes} ${ampm}`;
}

/**
 * Show loading indicator
 * Displays a loading message while processing
 * 
 * @param {string} message - Loading message to display
 */
function showLoading(message) {
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-indicator';
    loadingDiv.className = 'loading';
    loadingDiv.innerHTML = `
        <div class="loading-spinner"></div>
        <p>${message || 'Processing...'}</p>
    `;
    document.body.appendChild(loadingDiv);
}

/**
 * Hide loading indicator
 * Removes the loading message
 */
function hideLoading() {
    const loadingDiv = document.getElementById('loading-indicator');
    if (loadingDiv) {
        loadingDiv.remove();
    }
}

/**
 * Validate PDF file
 * Checks if uploaded file is a valid PDF
 * 
 * @param {File} file - File object to validate
 * @returns {boolean} True if file is valid PDF
 */
function validatePDFFile(file) {
    if (!file) return false;
    
    // Check file extension
    const extension = file.name.split('.').pop().toLowerCase();
    if (extension !== 'pdf') {
        alert('Please upload a PDF file.');
        return false;
    }
    
    // Check file size (16MB max)
    const maxSize = 16 * 1024 * 1024; // 16MB in bytes
    if (file.size > maxSize) {
        alert('File is too large. Maximum size is 16MB.');
        return false;
    }
    
    return true;
}

/**
 * Parse days of week string
 * Converts day abbreviations to array of day numbers
 * 
 * @param {string} daysStr - Day string (e.g., "MWF" or "Mon/Wed/Fri")
 * @returns {Array<number>} Array of day numbers (0=Monday, 6=Sunday)
 */
function parseDaysOfWeek(daysStr) {
    if (!daysStr) return [];
    
    const dayMap = {
        'M': 0, 'Mon': 0, 'Monday': 0,
        'T': 1, 'Tue': 1, 'Tuesday': 1,
        'W': 2, 'Wed': 2, 'Wednesday': 2,
        'Th': 3, 'Thu': 3, 'Thursday': 3,
        'F': 4, 'Fri': 4, 'Friday': 4,
        'S': 5, 'Sat': 5, 'Saturday': 5,
        'Su': 6, 'Sun': 6, 'Sunday': 6,
    };
    
    const days = [];
    const upper = daysStr.toUpperCase();
    
    // Simple parsing - can be enhanced
    for (let i = 0; i < upper.length; i++) {
        const char = upper[i];
        if (char === 'M' && (i === 0 || upper[i-1] !== 'T')) {
            days.push(0);
        } else if (char === 'T') {
            if (i + 1 < upper.length && upper[i+1] === 'H') {
                days.push(3); // Thursday
                i++;
            } else {
                days.push(1); // Tuesday
            }
        } else if (char === 'W') {
            days.push(2);
        } else if (char === 'F') {
            days.push(4);
        }
    }
    
    return [...new Set(days)].sort();
}

/**
 * Initialize editable fields functionality
 * Makes missing or reviewable fields clickable for inline editing
 */
function initEditableFields() {
    console.log('=== initEditableFields called ===');
    
    // First, find all editable fields and add direct click listeners
    const editableFields = document.querySelectorAll('.editable-field');
    console.log('Found', editableFields.length, 'editable fields');
    
    if (editableFields.length === 0) {
        console.warn('WARNING: No editable fields found! Check HTML structure.');
        return;
    }
    
    editableFields.forEach((field, index) => {
        console.log(`Setting up field ${index}:`, field.textContent.substring(0, 30), 'classes:', field.className, 'data-field-type:', field.getAttribute('data-field-type'));
        
        // Make sure cursor shows it's clickable
        field.style.cursor = 'pointer';
        field.style.userSelect = 'none';
        field.style.position = 'relative'; // Ensure it can receive clicks
        field.style.zIndex = '10'; // Make sure it's above other elements
        
        // Store reference for debugging
        field._isEditable = true;
        
        // Use onclick as primary handler (most reliable)
        field.onclick = function(e) {
            // Don't handle clicks on buttons or inside the edit form
            const target = e.target;
            if (target.closest('.inline-edit-form') || 
                target.closest('.btn-save') || 
                target.closest('.btn-cancel') ||
                target.closest('button') ||
                target.closest('input')) {
                console.log('Click on button/form element, ignoring editable field handler');
                return true; // Allow the click to proceed
            }
            
            console.log('=== onclick handler triggered ===', this);
            console.log('Event:', e);
            console.log('Field type:', this.getAttribute('data-field-type'));
            
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            
            if (!this.classList.contains('editing')) {
                console.log('Calling startEditing...');
                startEditing(this);
            }
            return false;
        };
        
        // Also add event listener as backup
        field.addEventListener('click', function(e) {
            // Don't handle clicks on buttons or inside the edit form
            const target = e.target;
            if (target.closest('.inline-edit-form') || 
                target.closest('.btn-save') || 
                target.closest('.btn-cancel') ||
                target.closest('button') ||
                target.closest('input')) {
                console.log('Click on button/form element (addEventListener), ignoring');
                return true; // Allow the click to proceed
            }
            
            console.log('addEventListener click on field:', this);
            e.preventDefault();
            e.stopPropagation();
            if (!this.classList.contains('editing')) {
                startEditing(this);
            }
            return false;
        }, true); // Capture phase
        
        // Prevent form submission when clicking
        field.addEventListener('mousedown', function(e) {
            console.log('mousedown on field');
            e.stopPropagation();
        }, true);
    });
    
    console.log('=== Finished setting up editable fields ===');
}

/**
 * Start editing a field
 * Replaces the field display with an input form
 * 
 * @param {HTMLElement} fieldElement - The field element to edit
 */
function startEditing(fieldElement) {
    console.log('startEditing called with:', fieldElement);
    
    if (!fieldElement) {
        console.error('startEditing: fieldElement is null or undefined');
        return;
    }
    
    // Don't start editing if already in edit mode
    if (fieldElement.classList.contains('editing')) {
        console.log('Field already in editing mode, skipping');
        return;
    }
    
    const fieldType = fieldElement.getAttribute('data-field-type');
    let currentValue = fieldElement.getAttribute('data-current-value') || '';
    
    // For assessment_title, extract text from <strong> tag if data attribute is empty
    if (fieldType === 'assessment_title' && !currentValue) {
        const strongTag = fieldElement.querySelector('strong');
        if (strongTag) {
            currentValue = strongTag.textContent.trim();
        }
    }
    
    const assessmentIndex = fieldElement.getAttribute('data-assessment-index');
    
    console.log('Field details:', { fieldType, currentValue, assessmentIndex });
    
    // Determine input type based on field type
    let inputType = 'text';
    let placeholder = '';
    let inputValue = currentValue;
    
    if (fieldType === 'term_start' || fieldType === 'term_end') {
        inputType = 'date';
        // For date fields, just use the date part
        if (currentValue && currentValue.includes('T')) {
            inputValue = currentValue.split('T')[0];
        } else if (currentValue && currentValue.includes(' ')) {
            inputValue = currentValue.split(' ')[0];
        } else {
            inputValue = currentValue;
        }
        placeholder = 'YYYY-MM-DD';
    } else if (fieldType === 'assessment_due_date') {
        inputType = 'datetime-local';
        // Convert YYYY-MM-DD to datetime-local format if needed
        if (currentValue && !currentValue.includes('T') && !currentValue.includes(' ')) {
            inputValue = currentValue + 'T00:00';
        } else if (currentValue && currentValue.includes(' ')) {
            inputValue = currentValue.replace(' ', 'T');
        }
        placeholder = 'YYYY-MM-DD HH:MM';
    } else if (fieldType === 'assessment_weight') {
        inputType = 'number';
        inputValue = currentValue;
        placeholder = 'Enter weight (%)';
    } else if (fieldType === 'assessment_lead_time') {
        inputType = 'number';
        inputValue = currentValue;
        placeholder = 'Enter lead time (days)';
        min = 0;  // Lead time must be non-negative
    } else if (fieldType === 'lead_time_mapping') {
        inputType = 'number';
        inputValue = currentValue;
        placeholder = 'Enter lead time (days)';
        min = 0;  // Lead time must be non-negative
    } else if (fieldType === 'assessment_title') {
        inputType = 'text';
        inputValue = currentValue;
        placeholder = 'Enter assessment title';
    } else {
        placeholder = 'Enter value';
    }
    
    // Create input form - make sure it doesn't submit parent form
    const editForm = document.createElement('form');
    editForm.className = 'inline-edit-form';
    editForm.style.display = 'inline-block';
    editForm.style.position = 'relative';
    editForm.style.zIndex = '1000';
    editForm.onsubmit = function(e) {
        console.log('Edit form onsubmit handler called');
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        return false;
    };
    // Build min/max/step attributes for number inputs
    let numberAttrs = '';
    if (inputType === 'number') {
        if (fieldType === 'assessment_weight') {
            numberAttrs = 'min="0" max="100" step="0.1"';
        } else if (fieldType === 'assessment_lead_time' || fieldType === 'lead_time_mapping') {
            numberAttrs = 'min="0" step="1"';
        } else {
            numberAttrs = 'min="0"';
        }
    }
    
    editForm.innerHTML = `
        <div class="inline-edit-container">
            <input type="${inputType}" 
                   class="inline-edit-input" 
                   value="${inputValue}" 
                   placeholder="${placeholder}"
                   ${numberAttrs}
                   autofocus>
            <div class="inline-edit-buttons">
                <button type="submit" class="btn-save save-btn" style="pointer-events: auto; z-index: 1001;">Save</button>
                <button type="button" class="btn-cancel cancel-btn" style="pointer-events: auto; z-index: 1001;">Cancel</button>
            </div>
        </div>
    `;
    
    // Store original content
    const originalContent = fieldElement.innerHTML;
    const originalDisplay = fieldElement.style.display;
    
    // Store original content as attribute for later retrieval
    fieldElement.setAttribute('data-original-content', originalContent);
    
    // Replace field with form
    fieldElement.innerHTML = '';
    fieldElement.appendChild(editForm);
    fieldElement.classList.add('editing');
    
    console.log('Edit form created and appended:', editForm);
    
    const input = editForm.querySelector('.inline-edit-input');
    const saveBtn = editForm.querySelector('.btn-save');
    const cancelBtn = editForm.querySelector('.btn-cancel');
    
    console.log('Form elements found:', { input: !!input, saveBtn: !!saveBtn, cancelBtn: !!cancelBtn });
    
    if (input) {
        // Use setTimeout to ensure focus works after DOM update
        setTimeout(() => {
            input.focus();
            input.select();
        }, 10);
    }
    
    // Handle form submission - prevent bubbling to parent form
    editForm.addEventListener('submit', function(e) {
        console.log('Edit form submit event triggered');
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        const newValue = input.value.trim();
        console.log('Saving field:', fieldType, 'new value:', newValue);
        saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
        return false;
    }, true); // Use capture phase
    
    // Handle save button click directly (in case form submit doesn't work)
    // saveBtn is already declared above, so just use it
    if (saveBtn) {
        // Use both capture and bubble phases to ensure we catch the event
        saveBtn.addEventListener('click', function(e) {
            console.log('Save button clicked - handler 1');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            const newValue = input.value.trim();
            console.log('Saving field via button:', fieldType, 'new value:', newValue);
            saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
            return false;
        }, true); // Capture phase
        
        saveBtn.addEventListener('click', function(e) {
            console.log('Save button clicked - handler 2');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            const newValue = input.value.trim();
            console.log('Saving field via button (bubble):', fieldType, 'new value:', newValue);
            saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
            return false;
        }, false); // Bubble phase
        
        // Also use onclick as a fallback
        saveBtn.onclick = function(e) {
            console.log('Save button onclick handler');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            const newValue = input.value.trim();
            saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
            return false;
        };
    }
    
    // Handle cancel
    // cancelBtn is already declared above, so just use it
    if (cancelBtn) {
        // Use both capture and bubble phases to ensure we catch the event
        cancelBtn.addEventListener('click', function(e) {
            console.log('Cancel button clicked - handler 1');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            fieldElement.innerHTML = originalContent;
            fieldElement.classList.remove('editing');
            return false;
        }, true); // Capture phase
        
        cancelBtn.addEventListener('click', function(e) {
            console.log('Cancel button clicked - handler 2');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            fieldElement.innerHTML = originalContent;
            fieldElement.classList.remove('editing');
            return false;
        }, false); // Bubble phase
        
        // Also use onclick as a fallback
        cancelBtn.onclick = function(e) {
            console.log('Cancel button onclick handler');
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            fieldElement.innerHTML = originalContent;
            fieldElement.classList.remove('editing');
            return false;
        };
    }
    
    // Handle escape key
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                console.log('Escape pressed');
                fieldElement.innerHTML = originalContent;
                fieldElement.classList.remove('editing');
            } else if (e.key === 'Enter') {
                // Auto-save on Enter key
                e.preventDefault();
                const newValue = input.value.trim();
                if (newValue || fieldType === 'assessment_due_date' || fieldType === 'term_start' || fieldType === 'term_end') {
                    // Allow empty dates to be saved (clears the field)
                    console.log('Enter pressed - auto-saving field');
                    saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
                }
            }
        });
        
        // Auto-save on blur (when user clicks outside) - especially important for date inputs
        input.addEventListener('blur', function(e) {
            // Use setTimeout to allow click events on save/cancel buttons to fire first
            setTimeout(() => {
                // Check if we're still in editing mode (buttons might have already saved/cancelled)
                if (fieldElement.classList.contains('editing')) {
                    const newValue = input.value.trim();
                    // For date fields, allow saving even if empty (to clear the date)
                    if (newValue || fieldType === 'assessment_due_date' || fieldType === 'term_start' || fieldType === 'term_end') {
                        console.log('Input blurred - auto-saving field');
                        saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent);
                    } else {
                        // If no value and not a date field, cancel the edit
                        console.log('Input blurred with no value - cancelling edit');
                        fieldElement.innerHTML = originalContent;
                        fieldElement.classList.remove('editing');
                    }
                }
            }, 200); // Small delay to let button clicks process first
        });
    }
}

/**
 * Save field value to server
 * 
 * @param {HTMLElement} fieldElement - The field element
 * @param {string} fieldType - Type of field being edited
 * @param {string} newValue - New value to save
 * @param {string} assessmentIndex - Assessment index if editing assessment
 * @param {string} originalContent - Original HTML content to restore on error
 */
function saveField(fieldElement, fieldType, newValue, assessmentIndex, originalContent) {
    // Show loading state
    fieldElement.innerHTML = '<span class="saving">Saving...</span>';
    
    // Prepare request data
    const requestData = {
        field_type: fieldType,
        value: newValue || null
    };
    
    if (assessmentIndex !== null) {
        requestData.assessment_index = parseInt(assessmentIndex);
    }
    
    // For lead time mapping, include the weight range
    if (fieldType === 'lead_time_mapping') {
        const weightRange = fieldElement.getAttribute('data-weight-range');
        if (weightRange) {
            requestData.weight_range = weightRange;
        }
    }
    
    // Send update request
    fetch('/api/update-field', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update display with new value
            updateFieldDisplay(fieldElement, fieldType, newValue);
            // Show success message briefly
            fieldElement.classList.add('saved');
            setTimeout(() => {
                fieldElement.classList.remove('saved');
            }, 2000);
        } else {
            // Show error and restore original
            alert('Error: ' + (data.error || 'Failed to save'));
            fieldElement.innerHTML = originalContent;
            fieldElement.classList.remove('editing');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error saving field. Please try again.');
        fieldElement.innerHTML = originalContent;
        fieldElement.classList.remove('editing');
    });
}

/**
 * Update field display after successful save
 * 
 * @param {HTMLElement} fieldElement - The field element
 * @param {string} fieldType - Type of field
 * @param {string} newValue - New value
 */
function updateFieldDisplay(fieldElement, fieldType, newValue) {
    let displayValue = newValue || 'Not found';
    
    // Format display based on field type
    if (fieldType === 'term_start' || fieldType === 'term_end') {
        if (newValue) {
            // Extract date part (YYYY-MM-DD) - already just a date
            displayValue = newValue.split('T')[0].split(' ')[0];
        } else {
            displayValue = 'Not found';
        }
    } else if (fieldType === 'assessment_due_date') {
        if (newValue) {
            // Format datetime for display
            const dt = new Date(newValue);
            displayValue = dt.toLocaleString('en-US', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } else {
            displayValue = 'Due date not found';
        }
    } else if (fieldType === 'assessment_weight') {
        if (newValue) {
            displayValue = newValue + '%';
        } else {
            displayValue = 'Not set';
        }
    } else if (fieldType === 'assessment_lead_time') {
        if (newValue) {
            displayValue = newValue + ' days';
        } else {
            displayValue = 'Not set';
        }
    } else if (fieldType === 'lead_time_mapping') {
        if (newValue) {
            displayValue = newValue + ' days before due';
        } else {
            displayValue = 'Not set';
        }
    } else if (fieldType === 'assessment_title') {
        displayValue = newValue || 'Untitled';
    } else if (fieldType === 'course_code' || fieldType === 'course_name') {
        displayValue = newValue || 'Not found';
    }
    
    // Update the field
    const isMissing = !newValue || newValue === '' || displayValue === 'Not found' || displayValue === 'Not set';
    
    // For assessment_title, preserve the <strong> tag structure
    if (fieldType === 'assessment_title') {
        fieldElement.innerHTML = `<strong>${displayValue}</strong>`;
    } else {
        fieldElement.innerHTML = displayValue;
    }
    
    fieldElement.setAttribute('data-current-value', newValue || '');
    
    if (isMissing) {
        fieldElement.classList.add('missing-field');
    } else {
        fieldElement.classList.remove('missing-field');
    }
    
    // Update completeness metrics without full page reload
    // The field display has been updated, so we're done
    // User can continue editing other fields
}

/**
 * Initialize manual section adders (for lecture and lab sections)
 * Handles the "Add Section Manually" buttons
 */
function initManualSectionAdders() {
    // Handle "Add Lab Section Manually" button
    const addLabBtn = document.getElementById('add-lab-section');
    if (addLabBtn) {
        addLabBtn.addEventListener('click', function() {
            showManualSectionForm('lab');
        });
    }
    
    // Handle "Add Lecture Section Manually" button
    const addLectureBtn = document.getElementById('add-lecture-section');
    if (addLectureBtn) {
        addLectureBtn.addEventListener('click', function() {
            showManualSectionForm('lecture');
        });
    }
}

/**
 * Show form modal for adding a manual section
 * 
 * @param {string} sectionType - 'lab' or 'lecture'
 */
function showManualSectionForm(sectionType) {
    // Create modal overlay using existing modal class
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    
    // Create modal content using existing modal-content class
    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content';
    
    const sectionName = sectionType === 'lab' ? 'Lab' : 'Lecture';
    
    modalContent.innerHTML = `
        <span class="close-modal">&times;</span>
        <h3>
            <i data-lucide="plus-circle"></i>
            Add ${sectionName} Section Manually
        </h3>
        <form id="manual-section-form">
            <div class="form-group">
                <label for="section-days">Days of Week:</label>
                <div class="days-checkbox-group">
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="0"> Mon
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="1"> Tue
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="2"> Wed
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="3"> Thu
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="4"> Fri
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="5"> Sat
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" name="day" value="6"> Sun
                    </label>
                </div>
                <small>Select one or more days when this ${sectionName.toLowerCase()} meets</small>
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="section-start-time">Start Time:</label>
                    <input type="time" id="section-start-time" name="start_time" required class="form-control">
                </div>
                <div class="form-group">
                    <label for="section-end-time">End Time:</label>
                    <input type="time" id="section-end-time" name="end_time" required class="form-control">
                </div>
            </div>
            
            <div class="form-group">
                <label for="section-location">Location (optional):</label>
                <input type="text" id="section-location" name="location" placeholder="e.g., UC 202" class="form-control">
            </div>
            
            <div class="form-actions">
                <button type="button" class="btn btn-secondary btn-cancel-modal">Cancel</button>
                <button type="submit" class="btn btn-primary">Add Section</button>
            </div>
        </form>
    `;
    
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    
    // Initialize Lucide icons in modal
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    // Handle form submission
    const form = modalContent.querySelector('#manual-section-form');
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Get selected days
        const dayCheckboxes = form.querySelectorAll('input[name="day"]:checked');
        if (dayCheckboxes.length === 0) {
            alert('Please select at least one day of the week.');
            return;
        }
        
        const days = Array.from(dayCheckboxes).map(cb => parseInt(cb.value)).sort();
        const startTime = form.querySelector('#section-start-time').value;
        const endTime = form.querySelector('#section-end-time').value;
        const location = form.querySelector('#section-location').value || null;
        
        if (!startTime || !endTime) {
            alert('Please enter both start and end times.');
            return;
        }
        
        // Add the section to the page
        addManualSection(sectionType, days, startTime, endTime, location);
        
        // Close modal
        modal.style.display = 'none';
        document.body.removeChild(modal);
    });
    
    // Handle close button
    const closeBtn = modalContent.querySelector('.close-modal');
    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            modal.style.display = 'none';
            document.body.removeChild(modal);
        });
    }
    
    // Handle cancel button
    const cancelBtn = modalContent.querySelector('.btn-cancel-modal');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            modal.style.display = 'none';
            document.body.removeChild(modal);
        });
    }
    
    // Close on overlay click
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            modal.style.display = 'none';
            document.body.removeChild(modal);
        }
    });
}

/**
 * Add a manually created section to the page
 * 
 * @param {string} sectionType - 'lab' or 'lecture'
 * @param {Array<number>} days - Array of day numbers (0=Mon, 6=Sun)
 * @param {string} startTime - Start time (HH:MM format)
 * @param {string} endTime - End time (HH:MM format)
 * @param {string|null} location - Location (optional)
 */
function addManualSection(sectionType, days, startTime, endTime, location) {
    const sectionName = sectionType === 'lab' ? 'Lab' : 'Lecture';
    const sectionId = sectionType === 'lab' ? 'lab_section' : 'lecture_section';
    
    // Find the section container - look for the h3 with the section name
    const sectionHeaders = document.querySelectorAll('.review-section-item h3');
    let sectionContainer = null;
    for (const header of sectionHeaders) {
        if (header.textContent.trim() === `${sectionName} Section`) {
            sectionContainer = header.closest('.review-section-item');
            break;
        }
    }
    
    // Fallback: find by button ID
    if (!sectionContainer) {
        const addButton = document.getElementById(`add-${sectionType}-section`);
        if (addButton) {
            sectionContainer = addButton.closest('.review-section-item');
        }
    }
    
    if (!sectionContainer) {
        console.error(`Could not find ${sectionName} section container`);
        return;
    }
    
    // Day names for display
    const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const dayDisplay = days.map(d => dayNames[d]).join('/');
    
    // Format time for display (convert 24h to 12h)
    const formatTime = (timeStr) => {
        const [hours, minutes] = timeStr.split(':');
        const hour = parseInt(hours);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const displayHour = hour % 12 || 12;
        return `${displayHour}:${minutes} ${ampm}`;
    };
    
    // Create the select dropdown if it doesn't exist
    let selectElement = document.getElementById(sectionId);
    if (!selectElement) {
        // Remove the "no data" message and button
        const noDataMsg = sectionContainer.querySelector('.no-data');
        const addButton = sectionContainer.querySelector(`#add-${sectionType}-section`);
        const hiddenInput = sectionContainer.querySelector('input[type="hidden"][name="' + sectionId + '"]');
        
        if (noDataMsg) {
            noDataMsg.remove();
        }
        if (addButton) {
            addButton.remove();
        }
        if (hiddenInput) {
            hiddenInput.remove();
        }
        
        // Create form group and select
        const formGroup = document.createElement('div');
        formGroup.className = 'form-group';
        formGroup.innerHTML = `
            <label for="${sectionId}">Select your ${sectionName.toLowerCase()} section:</label>
            <select name="${sectionId}" id="${sectionId}" class="form-control" ${sectionType === 'lecture' ? 'required' : ''}>
                <option value="none">-- ${sectionType === 'lab' ? 'No Lab Section' : 'Select Lecture Section'} --</option>
            </select>
        `;
        
        // Find the h3 header to insert after it
        const header = sectionContainer.querySelector('h3');
        if (header && header.nextSibling) {
            // Insert after the header, before any existing content
            sectionContainer.insertBefore(formGroup, header.nextSibling);
        } else {
            // Fallback: append to container
            sectionContainer.appendChild(formGroup);
        }
        
        selectElement = document.getElementById(sectionId);
        
        // Also add the button back (so user can add more sections)
        const buttonContainer = document.createElement('div');
        buttonContainer.style.marginTop = '10px';
        const addMoreButton = document.createElement('button');
        addMoreButton.type = 'button';
        addMoreButton.className = 'btn btn-secondary';
        addMoreButton.id = `add-${sectionType}-section`;
        addMoreButton.textContent = `+ Add Another ${sectionName} Section`;
        addMoreButton.addEventListener('click', function() {
            showManualSectionForm(sectionType);
        });
        buttonContainer.appendChild(addMoreButton);
        sectionContainer.appendChild(buttonContainer);
    }
    
    // Store manual sections in a hidden input for form submission
    let manualSectionsInput = document.getElementById(`manual_${sectionType}_sections`);
    if (!manualSectionsInput) {
        manualSectionsInput = document.createElement('input');
        manualSectionsInput.type = 'hidden';
        manualSectionsInput.id = `manual_${sectionType}_sections`;
        manualSectionsInput.name = `manual_${sectionType}_sections`;
        sectionContainer.appendChild(manualSectionsInput);
    }
    
    // Get existing manual sections
    const manualSections = [];
    const allOptions = selectElement.querySelectorAll('option[data-manual="true"]');
    allOptions.forEach(opt => {
        manualSections.push({
            days: JSON.parse(opt.getAttribute('data-days')),
            start_time: opt.getAttribute('data-start-time'),
            end_time: opt.getAttribute('data-end-time'),
            location: opt.getAttribute('data-location')
        });
    });
    
    // Add the new section
    manualSections.push({
        days: days,
        start_time: startTime,
        end_time: endTime,
        location: location || ''
    });
    
    // Update hidden input
    manualSectionsInput.value = JSON.stringify(manualSections);
    
    // Add option to select - use index as value for proper matching
    const option = document.createElement('option');
    const manualIndex = manualSections.length - 1; // Index in the manual sections array
    option.value = `manual_${manualIndex}`;
    option.textContent = `${dayDisplay} ${formatTime(startTime)}-${formatTime(endTime)}${location ? ` (${location})` : ''}`;
    option.setAttribute('data-days', JSON.stringify(days));
    option.setAttribute('data-start-time', startTime);
    option.setAttribute('data-end-time', endTime);
    option.setAttribute('data-location', location || '');
    option.setAttribute('data-manual', 'true');
    option.setAttribute('data-manual-index', manualIndex);
    
    selectElement.appendChild(option);
    
    // Select the newly added option
    option.selected = true;
}

// Initialize assessment add/remove functionality
function initAssessmentAddRemove() {
    // Add Assessment button
    const addBtn = document.getElementById('add-assessment-btn');
    if (addBtn) {
        addBtn.addEventListener('click', function() {
            showAddAssessmentModal();
        });
    }
    
    // Remove Assessment buttons
    const removeButtons = document.querySelectorAll('.btn-remove-assessment');
    removeButtons.forEach(button => {
        button.addEventListener('click', function() {
            const index = parseInt(this.getAttribute('data-assessment-index'));
            removeAssessment(index);
        });
    });
    
    // Modal close handlers
    const modal = document.getElementById('add-assessment-modal');
    if (modal) {
        const closeBtn = modal.querySelector('.close-modal');
        const cancelBtn = modal.querySelector('.cancel-add-assessment');
        
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                modal.style.display = 'none';
            });
        }
        
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                modal.style.display = 'none';
            });
        }
        
        // Close when clicking outside modal
        window.addEventListener('click', function(event) {
            if (event.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
    
    // Form submission - prevent default and stop propagation
    const form = document.getElementById('add-assessment-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            e.stopPropagation();
            addAssessment();
            return false;
        });
    }
}

function showAddAssessmentModal() {
    const modal = document.getElementById('add-assessment-modal');
    if (modal) {
        modal.style.display = 'block';
        // Reset form
        const form = document.getElementById('add-assessment-form');
        if (form) {
            form.reset();
        }
    }
}

function addAssessment() {
    const form = document.getElementById('add-assessment-form');
    if (!form) return;
    
    const formData = new FormData(form);
    const data = {
        title: formData.get('title'),
        type: formData.get('type'),
        weight_percent: formData.get('weight_percent') || null,
        due_datetime: formData.get('due_datetime') || null,
        due_rule: formData.get('due_rule') || null,
        rule_anchor: formData.get('rule_anchor') || null,
        confidence: 0.8,  // Default confidence for manually added assessments
        source_evidence: 'Manual entry',  // Default source for manually added assessments
        needs_review: false  // Default to false for manually added assessments
    };
    
    // Remove null/empty values (but keep confidence and source_evidence)
    Object.keys(data).forEach(key => {
        if (key !== 'confidence' && key !== 'source_evidence' && (data[key] === null || data[key] === '')) {
            delete data[key];
        }
    });
    
    fetch('/api/add-assessment', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            // Close modal
            const modal = document.getElementById('add-assessment-modal');
            if (modal) {
                modal.style.display = 'none';
            }
            
            // Reload page to show new assessment
            window.location.reload();
        } else {
            alert('Error adding assessment: ' + (result.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error adding assessment: ' + error.message);
    });
}

function removeAssessment(index) {
    if (!confirm('Are you sure you want to remove this assessment?')) {
        return;
    }
    
    fetch('/api/remove-assessment', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            assessment_index: index
        })
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            // Reload page to reflect changes
            window.location.reload();
        } else {
            alert('Error removing assessment: ' + (result.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error removing assessment: ' + error.message);
    });
}

