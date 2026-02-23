import matplotlib.pyplot as plt

# Create the main figure and axis
fig, ax = plt.subplots()

# Plot some sample data
ax.plot([0, 1, 2, 3, 4], [10, 20, 25, 30, 40], label='Main Data')

# Define the x-value for the vertical line
x_val = 2.55

# Draw the vertical line
ax.axvline(x=x_val, color='red', linestyle='--', label=f'x = {x_val}')

# Create a secondary x-axis (on top)
secax = ax.secondary_xaxis('top')
secax.set_xlabel('Secondary X-Axis')

# Optionally, customize tick marks or labels
secax.set_xticks([x_val])
secax.set_xticklabels([f'{x_val}'])

# # Add a text label at the vertical line position
# ymin, ymax = ax.get_ylim()
# ax.text(x_val, ymax * 0.95, f'x = {x_val}', color='red', rotation=90,
#         va='top', ha='center', backgroundcolor='white')

# Final touches
ax.set_title("Vertical Line with Secondary X-Axis")
# ax.legend()
plt.tight_layout()
plt.show()
