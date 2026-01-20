import os

def generate_udev_rules(serial_mapping):
    '''Generates a udev rules file for consistent mount naming.'''
    lines = []
    for name, serial in serial_mapping.items():
        rule = f'SUBSYSTEM=="tty", ATTRS{{serial}}=="{serial}", SYMLINK+="{name}", MODE="0666"'
        lines.append(rule)
    
    with open('99-telescopes.rules', 'w') as f:
        f.write('\n'.join(lines))
    
    print('Generated 99-telescopes.rules. Run the README instructions to apply.')

if __name__ == '__main__':
    # Update these serials as you receive your mounts
    my_serials = {
        'mount1': '4E9841685300',
        'mount2': 'YOUR_SERIAL_2',
        'mount3': 'YOUR_SERIAL_3',
        'mount4': 'YOUR_SERIAL_4'
    }
    generate_udev_rules(my_serials)